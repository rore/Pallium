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
- The smallest viable persistence is one fixed-shape activation-attempt relation row per `(attempt_id, delivery_id)` in the existing Relay SQLite database. Coalesced deliveries share one `attempt_id`; rows are associations to one attempt, not invented attempts. A row has bounded prepared/associated, immediate outcome, and optional later-resolution slots rather than an unbounded event stream. Stable projected event IDs derive from attempt ID, delivery ID, and stage.
- Existing delivery columns remain authoritative for immutable send-time target, claim/recovery count, current lease, expiry, and ACK. The projection synthesizes those transitions and never copies them into a competing ledger. Two diagnostic flags on the delivery distinguish per-delivery truncation and retention pruning; a nullable trace version distinguishes pre-feature legacy rows.
- Defaults proposed for review are eight activation attempts per delivery, thirty days, and 100,000 total attempt-association rows. At the observed peak day this is about 27,120 rows for thirty days even if every message reaches the eight-attempt cap, leaving about 3.7x headroom. A transactional row-count guard makes 100,000 a hard write bound even when the cleaner is disabled; the existing cleaner removes age/cap overflow in bounded batches. Reaching a bound drops diagnostics and marks the gap, never delivery state or native-write behavior.
- If the prerequisite cannot expose a stable attempt/correlation ID before native submission and the existing attempt outcome after it, stop and return to design; inferring coalescing from timestamps or pending-message scans is not acceptable.

**Plan:**
1. Land only after `add-relay-activation-capability-contract`: rebase onto its reviewed contract, consume its canonical attempt outcome/reason/retryability representation, and confirm one stable attempt ID plus destination generation crosses the adapter seam. Do not duplicate its capability projection or outcome mapping.
2. Add one Relay-local attempt relation record and additive legacy/gap fields to `storage/sqlite_schema.py`; initialize/migrate it through the existing Relay schema path. Implement idempotent, best-effort prepare/associate/complete/resolve writes and stable cursor reads in `storage/sqlite_relay.py`. Enforce eight attempts per delivery and a 100,000-row hard ceiling transactionally; duplicate exact facts are no-ops and conflicting/late facts remain bounded evidence rather than authority.
3. Extend `storage/sqlite_retention.py` and existing retention stats/logging so the current cleaner deletes trace rows older than thirty days and trims oldest rows above the total ceiling without touching messages, deliveries, claims, aliases, endpoint generations, or wake intents. Mark surviving deliveries as pruned before deleting their trace rows; repeated cleanup is idempotent.
4. Add optional best-effort trace recording and one shared bounded `trace_message` projection to `core/relay.py`. Wire the existing `app/dependencies.py` dispatch seam and the two current wake adapters to emit prepared, coalesced, normalized outcome, and authoritative late-resolution facts. Catch/log every diagnostic failure outside correctness transactions; preserve native submission, coalescing, ambiguous-write suppression, ACK, and recovery behavior byte-for-byte.
5. Expose `GET /relay/messages/{message_id}/trace` with `limit`, stable `after_sequence`, and frozen `as_of_sequence` pagination through `api/schemas.py`/`api/routes.py`. Add `PalliumMcpClient.relay_trace` and `pallium_relay_trace(message_id, cursor)` using the same service projection and existing MCP budget trimming. Unknown IDs remain 404; validation is 422; access follows the current service-global Relay message-ID contract and does not widen History/memory scope.
6. Have `app/dashboard.py` call the same service projection and lazily fetch the trace when existing message detail opens; update `app/dashboard.html` with a compact ordered timeline and deterministic explanation only. Show original selector/endpoint separately from current endpoint state, claim attempts separately from activation attempts, and explicit legacy, absent, truncated, pruned, and uncertain evidence labels. Do not add archive/search UI.
7. Add caller-surface E2E in a focused new trace test file plus adapter/retention regressions for send -> prepare/coalesce -> accepted/deferred/uncertain/failed -> late resolution -> natural claim/recovery -> ACK/reply/expiry -> cleanup. Cover duplicate/conflicting/late events, crash after prepare, concurrent sends, clock rollback/ties, stable pagination under append, empty/1/max/over-max limits, Unicode/redaction, alias transfer, closed/reactivated targets, unknown/legacy IDs, separate Relay DB, trace-write/read/cleanup failures, hard caps, and no extra native writes or delivery mutations.
8. Reconcile `docs/agent-relay.md`, `docs/http-api.md`, the phase-zero terminology if not already owned by the prerequisite, and this roadmap/board status only after evidence. Run focused nodes, affected subsystem files, `--lf`, workflow/redline checks, then `python -m pytest tests/ -x -q` once. Obtain independent smart result review, resolve every finding, open the PR, and wait for coordinated merge/restart instruction.
Stop and return to planning if implementation requires a generic event bus, a second cleaner/registry, adapter-to-storage imports, inferred coalescing, optimistic outcomes, or trace state in a correctness decision.

**Verification plan:**
When one native activation serves one or many deliveries, each HTTP/MCP/dashboard read groups the same attempt ID and generation without incrementing the receiver-claim counter -> controlled Codex/Claude adapter E2E and cross-surface exact projection assertions.
When an attempt is prepared, deferred, accepted, uncertain, failed, or authoritatively resolved later, the ordered projection preserves recorded causal order despite timestamp ties/rollback and never equates acceptance with admission -> fault-injected adapter and restart E2E.
When a natural turn claims, recovers a lease, ACKs/replies, or expires, the trace links the current authoritative delivery fields and remains read-only -> full HTTP/MCP/hook lifecycle E2E with state/native-call counters.
When writes, reads, or cleanup fail, the original send/wake/coalescing/claim/ACK result and native-write count remain unchanged; absence/gap is disclosed -> injected storage failure tests through caller surfaces.
When per-delivery, age, or global bounds apply, pagination remains stable, surviving delivery flags disclose truncation/pruning, cleanup is repeatable, and separate Relay DBs leave no trace orphans -> boundary and retention E2E.
When inputs are unknown, legacy, malformed, Unicode, redacted, aliased, transferred, closed, reactivated, or concurrently appended, all three surfaces return the same bounded contract with no payload/secrets/raw provider data -> public API/MCP/dashboard E2E.

**Plan review:**
Pending clean-context review after discovery and manager design feedback.

**Approvals:**
Pending explicit human approval of the reviewed High-risk plan.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Not started. Isolated branch `feat/relay-delivery-trace` was created from `origin/main` at `27313e4e`; workflow applicability required the normal path, and pre-edit redline classified the intended surface High risk before any code inspection or edit.
