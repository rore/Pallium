<!-- agent-workflow:start -->
**Outcome:**
Operators can inspect a bounded, non-secret, end-to-end evidence trail for one Relay delivery across persistence, activation, admission, and terminal delivery state without changing delivery correctness.

**Target:**
Pallium.

**Scope:**
Relay delivery-trace persistence and retention, shared correlation/projection semantics, HTTP and MCP read surfaces, dashboard presentation, focused lifecycle/E2E coverage, and the owning roadmap/docs.

**Constraints:**
Reuse the existing Relay store and cleaner; one shared projection must feed HTTP/MCP/dashboard; diagnostic writes are best-effort and can never fail, retry, or mutate delivery behavior; expose no payload text, secrets, claim tokens, receipts, or raw provider output; coordinate shared outcome vocabulary with `@pall-arc`; do not edit the prerequisite activation-contract worktree or merge/restart before coordination.

**Completion criteria:**
For any Relay delivery, the supported read surfaces shall show the same bounded, ordered evidence with explicit correlation, coalescing, retention/pruning, legacy-gap, and uncertain-outcome semantics; missing or failed diagnostics shall be visible as absence/gaps and shall not affect the delivery lifecycle; all observable edge cases shall have caller-surface E2E coverage.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Pre-edit redline identifies schema-as-code, shared Relay contract, and HTTP API changes requiring persistence-, architecture-, and API-review. The feature spans several adapters but remains one repository, one coherent delivery unit, and one independently verifiable outcome.

**Discovery:**
Current main has one authoritative Relay message/delivery store. `RelayDeliveryRecord.attempts` counts receiver claims, not native activation attempts; current claim, lease, delivery, expiry, immutable send-time endpoint, and endpoint-generation state already supply the authoritative lifecycle facts. `app/dependencies.py` is the single wake composition seam, while `app/codex_wake.py` and `app/claude_wake.py` own native submission/coalescing and emit only logs or correctness-registry state. Codex keeps an in-process per-session generation and suppresses duplicate queued writes until admission; Claude persists an exact-session `wake_inflight` generation and delivery ID. Neither provides a common queryable attempt ledger. Existing query-audit, historical-reuse, metrics, and promotion-event tables have unrelated authority, fields, retention, and privacy contracts, so reusing them would create a second interpretation rather than reuse a Relay facility. The dashboard already exposes message detail and immutable delivery targets; MCP status already has bounded output handling; the existing cleaner owns maintenance but is disabled by default. Local read-only traffic on 2026-09-12 showed 1,499 retained messages, 113 in the latest day, 609 in seven days, and 1,499 in thirty days. The prerequisite `feat/relay-activation-contract` Work Record defines `accepted|deferred|uncertain|failed`, keeps admission separate, and explicitly excludes persistence; its exact public field names and producer boundary remain under coordination with `@pall-arc`.

**Material assumptions:**
- Rebase on the prerequisite activation-contract change and import its canonical attempt outcome/reason/retryability types; this task will not define parallel enums or edit the prerequisite worktree.
- The smallest viable persistence is one immutable stage-event row per `(attempt_id, delivery_id, stage)` in the existing Relay SQLite database. Stages are `prepared`, `associated`, `completed`, and optional authoritative `resolved`; outcomes exist only on completed/resolved events. Coalesced deliveries share one `attempt_id`; association rows do not invent attempts. Each row gets its own recorded sequence, so late completion/resolution cannot mutate an earlier frozen page.
- Existing delivery columns remain authoritative for immutable send-time target, current claim/lease/delivery/expiry state, and the cumulative receiver-claim count. The projection may report that multiple claims imply recovery, but it cannot fabricate timestamps or order for overwritten historical claims. Current lifecycle state is a separately labeled live snapshot outside the frozen diagnostic-event page.
- Diagnostic completeness is always `best_effort`. A nullable trace version distinguishes pre-feature legacy rows; delivery flags disclose known per-delivery truncation or retention pruning. An unmarked partial write failure remains explicitly possible and is never presented as complete evidence.
- Defaults proposed for review are eight activation attempts / thirty-two stage events per delivery, thirty days, and 100,000 total stage rows. At the observed peak day, eight attempts with four stage rows each would be about 108,480 rows in thirty days, so the global ceiling intentionally dominates that pathological case; ordinary one-attempt traffic is about 13,560 rows. The existing cleaner process runs trace cleanup even when memory retention is disabled. At capacity, a short diagnostic transaction evicts the oldest row, marks its delivery pruned, and admits the new row; on lock contention it drops the new diagnostic fact instead. Delivery state and native-write behavior never depend on either path.
- Diagnostic persistence has a 25 ms maximum SQLite lock wait, no ordinary retry wrapper, and never runs while an adapter coalescing/capability lock is held. Reads use a nonmutating Relay query rather than `relay_message_status`, whose current implementation expires rows as a write side effect.
- If the prerequisite cannot expose a stable attempt/correlation ID before native submission and the existing attempt outcome after it, stop and return to design; inferring coalescing from timestamps or pending-message scans is not acceptable.

**Plan:**
1. Land only after `add-relay-activation-capability-contract`: rebase onto its reviewed contract, consume its canonical attempt outcome/reason/retryability representation, and confirm one stable attempt ID plus destination generation crosses the adapter seam. Do not duplicate its capability projection or outcome mapping.
2. Add one Relay-local immutable stage-event record plus nullable trace version and known-gap flags to `storage/sqlite_schema.py`; initialize/migrate it through the existing Relay schema path. In `storage/sqlite_relay.py`, make deterministic duplicate facts no-ops, reject conflicting facts as diagnostics only, and give every prepared/associated/completed/resolved event a recorded sequence. Enforce eight attempts / thirty-two rows per delivery and 100,000 rows total; at capacity evict one oldest event and mark its delivery pruned before inserting the new event.
3. Add a dedicated diagnostic transaction helper with a 25 ms SQLite lock wait and no standard Relay retry path. Invoke it only outside adapter correctness locks and catch failure at the composition boundary. Extend `storage/sqlite_retention.py`, `core/service.py`, retention stats, and cleaner logging so the existing cleaner process removes trace rows older than thirty days and trims cap overflow in bounded batches even when memory retention is disabled; it never touches messages, deliveries, claims, aliases, endpoint generations, or correctness-critical wake intents.
4. Add optional best-effort trace recording and one shared bounded, nonmutating `trace_message` projection to `core/relay.py`. Wire `app/dependencies.py` and current wake adapters to emit prepared, associated/coalesced, normalized outcome, and authoritative late-resolution facts only after leaving scheduler/registry locks. Preserve native submission, coalescing, ambiguous-write suppression, admission, ACK, and recovery behavior. A later ACK is delivery evidence, never retroactive proof that an uncertain native submission was accepted.
5. Expose `GET /relay/messages/{message_id}/trace` with `limit`, stable `after_sequence`, and frozen `as_of_sequence` pagination through `api/schemas.py`/`api/routes.py`. Each immutable stage has its own sequence; current authoritative lifecycle state is a live snapshot outside that frozen event window. Add `PalliumMcpClient.relay_trace` and `pallium_relay_trace(message_id, cursor)` using the same service projection and existing MCP budget trimming; continuation advances after the last event actually emitted. Unknown IDs remain 404; validation is 422; access follows the current service-global Relay message-ID contract and does not widen History/memory scope.
6. Have `app/dashboard.py` call the same nonmutating service projection and lazily fetch the trace when existing message detail opens; never reuse the mutating status helper. Update `app/dashboard.html` with a compact ordered timeline and deterministic explanation only. Show original selector/endpoint separately from current endpoint state, cumulative claim count and unavailable earlier claim chronology separately from activation attempts, and `best_effort` evidence with explicit legacy, absent, known-truncated, known-pruned, and uncertain labels. Do not add archive/search UI.
7. Add caller-surface E2E in a focused new trace test file plus adapter/retention regressions for send -> prepare/coalesce -> accepted/deferred/uncertain/failed -> late resolution -> natural claim/recovery -> ACK/reply/expiry -> cleanup. Cover three claims/two recoveries under clock rollback without invented timestamps; completion/late association/pruning between frozen pages; MCP trimming continuation; duplicate/conflicting/late events; crash after prepare; partial trace loss plus restart; real SQLite contention and a blocked callback near lease expiry; disabled-memory-retention age cleanup and continued traffic at capacity; expired pending/claimed trace-only reads that leave stored state/token unchanged; Unicode/redaction, alias transfer/lifecycle, unknown/legacy IDs, separate Relay DB, and no extra native writes or delivery mutations.
8. Reconcile `docs/agent-relay.md`, `docs/http-api.md`, the phase-zero terminology if not already owned by the prerequisite, and this roadmap/board status only after evidence. Run focused nodes, affected subsystem files, `--lf`, workflow/redline checks, then `python -m pytest tests/ -x -q` once. Obtain independent smart result review, resolve every finding, open the PR, and wait for coordinated merge/restart instruction.
Stop and return to planning if implementation requires a generic event bus, a second cleaner/registry, adapter-to-storage imports, inferred coalescing, optimistic outcomes, or trace state in a correctness decision.

**Verification plan:**
When one native activation serves one or many deliveries, each HTTP/MCP/dashboard read groups the same attempt ID and generation without incrementing the receiver-claim counter -> controlled Codex/Claude adapter E2E and cross-surface exact projection assertions.
When an attempt is prepared, deferred, accepted, uncertain, failed, or authoritatively resolved later, the ordered projection preserves recorded causal order despite timestamp ties/rollback and never equates acceptance with admission -> fault-injected adapter and restart E2E.
When a natural turn claims, recovers a lease, ACKs/replies, or expires, the trace shows only the current authoritative snapshot and cumulative claim count, labels prior claim chronology unavailable, and remains read-only -> three-claim/two-recovery HTTP/MCP/hook E2E with clock rollback and state/native-call counters.
When writes, reads, or cleanup fail or exceed 25 ms lock wait, the original send/wake/coalescing/claim/ACK result, lease handling, and native-write count remain unchanged; evidence stays explicitly best-effort and known gaps are disclosed when their marker persisted -> contention, partial-loss/restart, and injected failure tests through caller surfaces.
When per-delivery, age, or global bounds apply, immutable-event pagination remains frozen under append/prune, surviving delivery flags disclose known truncation/pruning, cleanup runs through the existing cleaner even with memory retention disabled, and separate Relay DBs leave no trace orphans -> boundary and retention E2E.
When inputs are unknown, legacy, malformed, Unicode, redacted, aliased, transferred, closed, reactivated, or concurrently appended, all three surfaces return the same bounded contract with no payload/secrets/raw provider data -> public API/MCP/dashboard E2E.

**Plan review:**
Clean-context review of `7bcd6c55` by `/root/delivery_trace_plan_review` returned revise-before-implementation. Addressed in this revision: no fabricated historical claim chronology; explicit always-best-effort completeness; immutable stage-event sequences and frozen-page/MCP continuation semantics; 25 ms no-retry diagnostic transactions outside correctness locks; trace cleanup in the existing cleaner even when memory retention is disabled; nonmutating trace reads; and the six required contention/interleaving E2E cases. Re-review remains pending after `@pall-arc` and manager feedback settles the shared producer contract.

**Approvals:**
Pending explicit human approval of the reviewed High-risk plan.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Not started. Isolated branch `feat/relay-delivery-trace` was created from `origin/main` at `27313e4e`; workflow applicability required the normal path, and pre-edit redline classified the intended surface High risk before any code inspection or edit.
