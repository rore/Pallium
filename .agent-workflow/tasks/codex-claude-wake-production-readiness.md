<!-- agent-workflow:start -->
**Outcome:**
S1A is complete: the installed no-human Windows witness proved a peer Relay message was claimed by Stop, injected through attributed stderr and exit 2, and answered without another human prompt. The next blocker is S1B restart durability: service restart loses the memory-only Claude registration and leaves delivery pending until a manual wake re-registers it.

**Target:**
Pallium Claude Code Relay availability.

**Scope:**
S1A changes are complete. S1B implements the accepted trusted-local exact-capability lifecycle. The proposed state distinguishes `idle`, `busy`, and `wake_inflight` with delivery id and UTC attempt time; it persists registration/idle/inflight mutations before publication or transport, fails closed to in-memory busy when busy persistence fails, and includes a one-file-per-session write-ahead registration intent from the hook, never claims or ACKs during recovery, and retains Relay as the source of once-only delivery truth. Every Stop registers idle with existing exact session/container/actor derivation. If `stop_hook_active` is false, call scoped `/relay/turn`; route admission marks busy. Send `max_chars=2400` in every non-recursive `/relay/turn` POST; storage is the authoritative claim boundary and skips over-budget items while retaining later fitting items pending/claimable. Stop candidate-renders exactly the returned claimed set without a second formatter cap; ACK each candidate; reformat only the ACK-success subset for attributed stderr and exit 2 only when that subset is nonempty. If recursive, empty, failed, invalid, or render-empty, ingest and exit 0. Preserve unrelated `uv.lock` and `.agent-workflow/.hooks.log`; no PR.

**Constraints:**
Peer text -> Stop -> one scoped `/relay/turn` POST with authoritative `max_chars=2400` -> candidate render of the returned claimed set -> individual ACK -> reformat successful subset -> exit 2 -> continuation acts -> next Stop re-registers idle, ingests, exits 0. Native transport never changes delivery. Existing Stop scope is authoritative; no MCP or model scope/identity. One bounded non-recursive Stop probe is accepted; `stop_hook_active` prevents recursion. Empty/failure/render-empty/all-ACK-failure exits 0; unACKed claimed items stay lease-recoverable. `has_more` and `remaining_count` remain pending and are unqualified until S1B rearm/continuation; the S1A witness proves one bounded batch only. S1A introduced none of those durable mechanisms. The S1B plan is the narrow exception: one trusted-local exact-capability file, one durable fail-closed rehydration marker, plus one atomic per-session write-ahead hook registration-intent file, a read-only exact-scope pending candidate query, event-driven reconciliation, best-effort SessionEnd/strictly-missing-endpoint cleanup, and explicit idle/busy/wake_inflight state. It still forbids DPAPI, a secret table, generic framework, claim/ACK during recovery, silent age eviction, alternate delivery paths, and secrets in logs.

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

S1B — ACTIVE: implement the accepted persistence, intent, fail-closed rehydration, read-only recovery query, and reconciler before the installed witness.

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
Approved by user 2026-09-03: "you have blanket approval for all tasks you get from the architect". Codex architect re-review CLEAN 2026-09-03; installed S1A runtime witness PASS. Architect accepted S1B plan b1991dc5 as CLEAN 2026-09-03 and authorized implementation; no Claude use, integration install/restart, PR, or merge is authorized.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-09-03 — S1B implementation started from accepted plan b1991dc5. Planned shared-path files: core/claude_wake.py, app/claude_wake.py, app/dependencies.py, api/routes.py, core/relay.py, Relay storage, Claude hook registration/SessionEnd files, and focused caller-surface tests. Scope excludes Claude execution, integration service changes, PR, and merge.
2026-09-03 — First shared-path slice replaces production memory-only capability state with trusted-local canonical persistence, write-ahead hook intents, exact intent matching, fail-closed busy fencing, non-admitting POSIX-only capacity reclamation, and startup read-only Relay recovery. Existing Stop caller-surface assertions now explicitly cover its required post-admission rearm.
2026-09-03 — Added closed-intent SessionEnd path, exact-scope read-only candidate E2E, and an app-local capped Event reconciler for persisted registries. Tests now isolate trusted-local state through PALLIUM_CLAUDE_WAKE_DIR; production still defaults to the canonical user-profile path.
2026-09-03 — Architect review rejected the first S1B implementation; remediation is in progress: focused Claude/Relay suites pass (127 passed, 2 skipped); the full suite has only the pre-existing `tests/test_config.py::test_prompt_variants_legacy_fallback_unaffected` failure. No installed Claude integration, service restart, or runtime witness was performed; the new SessionEnd helper remains uninstalled by scope.

2026-09-03 — Implemented S1A: non-recursive Claude Stop probes scoped `/relay/turn` once with `max_chars=2400`, renders exactly the returned claimed set without a formatter cap, ACKs individually, re-renders only 2xx-confirmed items to stderr, and exits 2 only for that nonempty subset. Recursive Stop re-registers idle without a probe. `acknowledge_relay` now returns only confirmed deliveries while existing callers may ignore the return. Architect re-review fixed empty/request/render/all-ACK-failure rearm after route admission, non-UTF-8 stderr buffer emission, and exact storage/hook template budgeting. Focused caller-surface regressions and exact storage/Claude boundary regression pass. Module-form affected suite, relay E2E, and isolation counts are recorded by final verification. Workflow and diff checks clean. `ruff` is unavailable in the environment. Architect re-review and installed S1A witness are PASS. Overall work is blocked on S1B restart durability planning and its eventual implementation/witness.
## S1B amended plan (plan only; no runtime edits)

**Incident / redline:** Service outage during Claude Stop is a distinct lost-handoff window: the hook's loopback registration fails, Claude becomes idle, and a later restart can reload stale `busy` forever. Durable capability and intent files may contain socket/token material, so no secret value, path, or token enters logs, exceptions, status, or tests. Relay remains authoritative for delivery; persistence/reconciliation never claims, ACKs, or emits it.

1. Canonical exact capability lives at `~/.pallium/claude-wake/capabilities.json` (Windows `%USERPROFILE%\.pallium\claude-wake\capabilities.json`) with runtime/session/container/actor, socket/token, generation, and `{busy, idle, wake_inflight(delivery_id, utc_attempt_time)}`. Atomic sibling replace; POSIX directory/file `0700`/`0600`; Windows inherits user-profile ACL, with no DPAPI/custom DACL. The existing registry lock serializes normal registration, same-session intent take/apply/removal, and state changes. Permissions are hygiene: malformed/invalid records are ignored, but a valid record is never discarded solely because permission-setting later reports failure.
2. Add the smallest cross-platform outage handoff: `~/.pallium/claude-wake/intents/<sha256(session_ref)>.json`. Before every hook HTTP registration attempt, atomically write the exact per-session intent and random `intent_id`, then include that id in the registration request. Under the registry lock, the request id must equal the currently stored same-session intent before **any** canonical mutation; mismatch is reject/no-op. Only then does successful server registration durably apply canonical state and consume that exact intent. An ambiguous/lost response leaves the original intent in place and may retry the same id, but never creates or rewrites an intent after the response. Crash before intent means no registration; crash after intent/before HTTP leaves recoverable intent; crash after canonical write/before exact consume leaves an idempotently recoverable intent; response loss after successful consume never produces a stale idle rewrite. Test A intent → B intent/applied → delayed A request as a deterministic mismatch no-op.
3. There is no TTL or age-based cleanup. Exact hook registration replaces canonical state only through the locked durable path. Best-effort online SessionEnd removes its exact record; SessionEnd reached during outage writes a closed/removal intent for that session. The 256-record cap never silently evicts: only under capacity pressure, run a non-admitting endpoint-absence check—never `registry.probe`, authentication, write, open, or another action that can admit a turn. An existing POSIX socket node and a busy/timeout Windows pipe are uncertainty and stay retained; delete only a provably absent endpoint, otherwise reject new registration. Only observed SessionEnd or a truly missing endpoint is terminal and deletes. Typed transport is conservative: `accepted` stays inflight pending observation; `retryable` restores idle; `terminal` means only missing endpoint and deletes. Permission denied, timeout, malformed transport response, and all other uncertainty are retryable.
4. Persistence failure is state-specific. Failed idle registration does not publish idle; failed idle→inflight does not write transport. Ordinary idle/inflight publication follows canonical atomic write. Failed busy persistence must immediately mark the in-memory capability busy, mark durability degraded, and make any stale durable idle record unloadable before continuing. If quarantine/delete cannot succeed, persist one durable fail-closed `store-unusable` marker checked before any startup capability load; no capabilities rehydrate until trusted registration or intent repair clears it. If neither stale-idle quarantine nor the marker can persist, startup refuses capability rehydration while the stale file remains—never load stale idle. Every failure is sanitized/observable (`persistence_failed`), preserves a previously valid capability where possible, and never marks Relay delivery done. Test canonical registration, write-ahead intent write/take/apply/exact-consume/delete, busy/idle, idle→inflight, terminal delete, and every atomic replace failure.
5. Add the minimum read-only storage/service exact-scope pending-candidate query; it rechecks without claim/ACK and distinguishes pending from claimed/delivered/expired. Recovery checks it after restart: claimed/delivered/expired clears inflight retry; pending inflight waits one bounded grace then retries. Crashes before persistence, after inflight persistence/before native write, and after native write prefer at most an extra empty admission over lost work; Relay action remains once-only.
6. Use one small event-driven reconciler, signaled by service readiness, new Relay send, successful registration, and intent consumption. Its Condition/Event wait uses a capped timeout and periodically scans write-ahead intents, covering a hook crash after intent or a post-start HTTP failure with no service signal. Signals coalesce through existing registry workers. While exact pending work and matching eligible idle/inflight capability remain, retries continue indefinitely with capped backoff and no busy loop, finite retry count, or human/new-send dependency. Retryable transport restores idle; accepted stays inflight until read-only observation; terminal deletes only under the strict rule above.
7. Deterministic fast E2E: A intent → B applied → delayed A mismatch; write-ahead hook crashes before intent, after intent/before HTTP, after server canonical write/before exact intent consume, and response loss after successful consume; no stale intent rewrite after ambiguity; busy-persistence failure then process restart with stale file present and marker/rehydration refusal; offline SessionEnd closed/removal cleanup; crash without SessionEnd filling capacity; live endpoint at capacity produces zero native transport writes/admissions; post-start intent discovery; each state-specific persistence write failure; corrupt intent/capability; Unicode paths; duplicate registration/concurrent send; accepted/retryable/terminal classification; infinite eligible retry with capped interval; and exact query never claiming/ACKing. Final real Windows witness: register idle → restart/outage or already-pending exact delivery → native wake → Stop claim/inject/reply, with no manual re-registration or user prompt.
**S1B review gate:** This amended plan is NOT CLEAN until Codex accepts the compare-before-apply write-ahead intents, durable fail-closed rehydration, non-admitting capacity cleanup, read-only query, and indefinite bounded-backoff reconciliation. S1A remains complete; overall status is Blocked only on S1B restart durability.
2026-09-03 — Remediation records explicit typed transport, post-start intent scans, exact close protection, malformed-record rejection, rejected loopback registration, and reconciler stop/join coverage. If every stale-file quarantine and marker write fails, the process reports durability degraded and does not claim automatic restart recovery; no filesystem primitive can prove that future restart state.
2026-09-03 — S1B slice 3 adds a real app-lifespan, post-start lost-loopback intent E2E: public Relay send signals reconciliation, imports the durable intent, invokes native transport once, leaves Relay pending, and joins the reconciler on shutdown.
2026-09-03 — S1B slice 4 adds a real SQLite expired-lease recovery E2E: read-only effective pending rechecks a stale claim, rollback rearms one native retry, and preserves the Relay claim/token/receipt/attempt row until normal turn reclaim.
2026-09-03 — S1B slice 5 qualifies SessionEnd setup, exact online close, and outage close-intent recovery: a stale close removes only its old capability while preserving a newer same-session registration intent.
2026-09-03 — S1B slice 6 aligns typed native outcomes with deterministic POSIX/Windows fake transport and non-admitting capacity coverage; only proven missing endpoints are terminal/reclaimed.
2026-09-03 — S1B slice 7 proves a persisted idle Claude capability and pending Relay delivery automatically wake exactly once through a real app restart, while Relay remains pending and unclaimed.
2026-09-03 — S1B slice 8 extends restart recovery through the actual Claude Stop hook: exact pending claim, attributed exit-2 output, one ACK/delivery, and duplicate-stop idle rearm without re-emission.
2026-09-03 — S1B slice 9 proves canonical-write failures reject idle registration while retaining write-ahead recovery, and fence an idle-to-inflight attempt before native transport or Relay mutation.
2026-09-03 — S1B slice 10 proves post-transport retryable and terminal canonical-write failures retain durable inflight state, rearm after restart/grace, and permit a later accepted retry without Relay mutation.
2026-09-03 — S1B slice 11 makes failed wake-intent atomic publication remove credential-bearing temp state before any loopback request, leaving no restart-visible intent.
2026-09-03 — S1B slice 12 validates encoded credential-body size before intent publication, retaining write-ahead-before-HTTP for normal Unicode registrations.
2026-09-03 — S1B slice 13 qualifies persisted inflight cleanup against active claimed, delivered, and expired Relay states through real SQLite/public status: recovery sends no native wake, clears only durable inflight state, preserves Relay state, and a fresh exact-scope delivery schedules one wake.
