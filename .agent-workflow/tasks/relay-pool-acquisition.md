# Relay connection-pool availability

Owner: @pal-dev1. Branch: feat/relay-pool-acquisition. Checkout: C:/Dev/rore/Pallium/build/relay-pool-acquisition-20261023. Base: verified current main 2768022ebf8b302d09a9955da38f3fc5d61504a4.

<!-- agent-workflow:start -->
**Outcome:** Relay connection-pool exhaustion returns a bounded retryable response instead of a 30-second unhandled HTTP 500.

**Target:** Pallium Relay SQLite acquisition.

**Scope:** storage/sqlite.py Relay engine/pool ownership, storage/sqlite_queue.py bounded acquisition error propagation, core/errors.py diagnostic classification, focused storage and HTTP E2E tests, docs/agent-relay.md, and this Work Record.

**Constraints:** Preserve unrelated database callers' configured pool policy, SQLite file/schema identity, transaction/claim/ACK fences, existing acquisition allowance, and memory-database compatibility. No arbitrary error masking, abandoned work after refusal, timeout increases, dependency/CI/protected-contract edits or live environment changes. Keep the original Linux CI 503 cause unknown and all prior red receipts intact.

**Completion criteria:** With an isolated file-based Relay pool exhausted, the HTTP caller receives retryable 503 with Retry-After within a documented realistic pool-admission budget, no refused turn is persisted, handles/gates are released, and recovery succeeds. Empty/near-capacity/full capacity, repeated recovery, split/co-located database ownership, unrelated errors and ordinary main-pool behavior have meaningful coverage.

**Requirement baseline:** {"source":"manager chat 01a16320-c588-72b0-a098-cb3d137b1e75, focused production-correction assignment following accepted acquisition-pool-control-02","outcome":"Relay connection-pool exhaustion returns a bounded retryable response instead of a 30-second unhandled HTTP 500.","scope":"storage/sqlite.py Relay engine/pool ownership, storage/sqlite_queue.py bounded acquisition error propagation, core/errors.py diagnostic classification, focused storage and HTTP E2E tests, docs/agent-relay.md, and this Work Record.","constraints":"Preserve unrelated database callers' configured pool policy, SQLite file/schema identity, transaction/claim/ACK fences, existing acquisition allowance, and memory-database compatibility. No arbitrary error masking, abandoned work after refusal, timeout increases, dependency/CI/protected-contract edits or live environment changes. Keep the original Linux CI 503 cause unknown and all prior red receipts intact.","completion_criteria":"With an isolated file-based Relay pool exhausted, the HTTP caller receives retryable 503 with Retry-After within a documented realistic pool-admission budget, no refused turn is persisted, handles/gates are released, and recovery succeeds. Empty/near-capacity/full capacity, repeated recovery, split/co-located database ownership, unrelated errors and ordinary main-pool behavior have meaningful coverage."}

**Relationships:** {"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Gray/watch storage and core-error paths alter connection-resource admission and classification; public schema, authorization and persistence formats stay unchanged. Shared/co-located and in-memory engine ownership require independent technical review.

**Discovery:** Accepted control 02 held all 15 private QueuePool handles: baseline POST 200/0.0131s, exhausted POST 500/30.0159s with native sqlalchemy.exc.TimeoutError code 3o7r, recovery GET 200/0.0118s, baseline only, zero checked-out handles and unlocked gate. Native source uses default QueuePool timeout 30s before the post-call 0.45s budget check. Ordinary callers share the main engine in supported co-located mode; in-memory pools must retain identity. Existing close/reclaim logic distinguishes engines by identity and needs source review if the Relay pool separates from the same database file.

**Material assumptions:** The supported SQLAlchemy poolclass/timeout APIs can isolate Relay pool admission without mutating shared timeout fields or using background cancellation. If preserving co-located/memory semantics needs unrelated policy changes, return the approach to review. The controlled failure establishes a mechanism, not the physical cause of original CI session_connection latency.

**Plan:** First implementation step: Invoke the /agent-workflow skill to create this Work Record and classify risk before any code edit (completed). Use SQLAlchemy's supported poolclass/pool_timeout construction: a small Relay-only QueuePool adapter uses timeout=0 and translates only native pool-timeout code 3o7r to ImmediateTransactionBusyError(pool_exhausted), preserving other exceptions. The main engine keeps its existing pool/30s policy. Existing separate file-based Relay databases reuse their own engine with this adapter; co-located file databases receive an independently owned Relay pool pointing at the same file, preserving main callers. Keep non-QueuePool/in-memory pools shared and unchanged. Preserve connect hooks, finite pool capacity, no background abandonment and existing acquisition retries/deadline. Retain pool_exhausted attribution through the bounded writer helper; map it through the existing domain-error HTTP503/Retry-After path without changing API routing/schema. Dispose owned engines on normal/failed construction; reclaim once per physical database rather than once per engine identity. Add focused real-pool HTTP E2E and storage lifecycle coverage, document the pool-admission budget and its scheduling/native-connect limits. Stop for review if isolation needs private mutable SQLAlchemy timeout fields, a new database, broad non-Relay policy changes or protected-contract edits. Independent plan review is required before product edits.

**Verification plan:** Bounded caller-visible pool refusal/recovery -> tests/test_relay_pool_exhaustion_e2e.py drives baseline/full-pool503/Retry-After/recovery through HTTP using actual finite handles and public session-list readback: split/co-located files, Unicode paths, empty/near/full capacity and at least three refusal/recovery cycles. Controlled warm refusal has a realistic 2s HTTP test envelope and configured pool wait zero; no hard450ms end-to-end promise.
Unrelated policy/errors and lifecycle preservation -> tests/test_sqlite_relay_isolation.py, tests/test_storage_sqlite.py, tests/test_sqlite_auto_vacuum.py and HTTP E2E verify main default30s policy, unchanged memory pool identity, same-file schema/data, one physical-file reclaim, constructor/normal disposal, Relay read refusal and unrelated native/custom TimeoutError propagation; the primary exhaustion failure uses real handles rather than fabricated errors. Preserve the existing engine observer's authorizer assertions while forwarding any new private factory options.
Write safety and budget preservation -> tests/test_sqlite_write_retry.py plus HTTP readback assert refused turns absent, gates/handles released, preserved pool-exhausted attribution, and unchanged acquisition/settlement boundaries.
Validation adequacy and evidence provenance -> Preserve both diagnostic attempts and accepted review; run focused files with -n 0 and affected Relay/storage/protected-contract cohorts only under reserved bounded executor slots. scripts/test-plan.py --base origin/main selects whole-change checks; run its required full non-slow lane once before PR and required CI. Reuse reliable unchanged evidence; no duplicate full run or unapproved runtime launch.

**Plan review:** Agent technical review: /root/relay_gate_plan_review, production-plan GO on efb4628857d01e6f13d7b6e7a02a58fe942b0c3a and 8d714a0615fc8f9870b6180d2557b48af6704540; see Plan review below. No blocking findings; implementation boundaries and verification accepted.

**Approvals:** Existing isolated reliability authority: user message 01a163d8-1ab3-7053-8639-f61daa6de2af in manager chat: "i approve all fixes for reliability and stability". Current manager assignment explicitly authorizes this focused production correction; no live rollout authority.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Evidence

Accepted read-only/controlled investigation: C:/Dev/rore/Pallium/build/codex-retained-idle-reenrollment-20261022/build/acquisition-pool-control-02/{recipe.json,observations.json,result.json,result-review.json,control-disposition.json}. Observations SHA256: 10d3086503be4e36f00a6847c1d35f85d6b30a1468e49b4aa6da206fb991b6db. Independent nonimplementer /root/rename_observer_review accepted consistency. Control 01 failed its harness basename precondition before any HTTP request or held handle; its original harness and receipt remain separately retained.

Original CI39906393631/c0bec620 retained log SHA256 3459f93c4b72e0f44b951f4bfec54abf8497edb1ae0c60d14262f4a46ff6565a: 3214 passed,29 skipped,1 xfailed,1 failed before malformed-incarnation mutation; /relay/turn503, setup_deadline1362ms/session_connection1360ms. Physical cause unknown. Windows installer WinError5 is a separate incident.

## Implementation

2026-10-23: Invoked workflow, inspected configured applicability/risk and created a clean branch from verified main. Complete mixed source/test scope is not documentation-exempt. State waits for the exact mechanism/independent plan review; no product source changed. Canonical roadmap remains manager-owned; report contribution there rather than creating another tracker. Current exact roadmap association already present and reused.

Pre-edit discovery: source caller search covers constructor, maintenance opener, all Relay session users, close and reclaim. Changing shared file-pool timeout globally would affect unrelated main callers; changing it temporarily would race. The proposed independently owned Relay pool is needed only when a file database previously shared the main pool. No extra pool is proposed for memory databases. Existing engine-identity reclaim would otherwise visit the same file twice, so preserve its file-level meaning. Documented transient database-busy handling currently omits the demonstrated native QueuePool timeout; unit fake-clock setup coverage does not exercise finite native pool exhaustion. These are source/docs/coverage gaps, not an attribution of the earlier CI latency.

Pre-edit boundary backend passed; intended-path Redline is GRAY with storage/core watch surfaces and no API/schema/visibility edits. The applicability checker requires the normal workflow for the mixed change. Technical mechanism review pending.

Caller discovery also found tests/test_storage_sqlite.py's private engine-factory wrapper. Update its option forwarding if the factory gains a Relay-only keyword; preserve existing schema/index authorizer assertions. SQLAlchemy's native dialect pool-class selection distinguishes file/URI memory behavior and avoids a new URL heuristic. No product edits or runtime tests have occurred.

## Plan review

Agent technical review: /root/relay_gate_plan_review. Reviewed revision: 8d714a0615fc8f9870b6180d2557b48af6704540 (initial context efb4628857d01e6f13d7b6e7a02a58fe942b0c3a), production source still unchanged. Decision: GO, no blocking architecture finding. Verification adequacy: the planned native-pool HTTP E2E, error-boundary, memory/URI, maintenance, lifecycle and ordinary-policy cases are adequate; include pool recovery between retries and preserve attribution without masking a later unrelated error.

The reviewer confirms a separate co-located file pool is necessary to preserve main callers, finite admission and all Relay read/write error handling without racing timeout mutation. Use native dialect pool-class selection, narrow 3o7r translation with cause retained, role-specific maintenance handling, all-owned-engine disposal and one reclaim per physical file. Preserve authorizer assertions in the private-factory wrapper. No new human approval is required under the existing isolated reliability authority. This review approves the plan only; focused/subsystem checks, required full/CI and result review remain open.

