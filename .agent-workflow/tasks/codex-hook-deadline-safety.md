# Hook deadline and audit-backlog safety

<!-- agent-workflow:start -->
**Outcome:**
Claude Code and Codex hooks finish within their host budgets without losing delivered Relay context, and assistant ingestion no longer waits on usage-audit fan-out.

**Target:**
Pallium hook integrations and the server ingestion boundary.

**Scope:**
Shared Python hook I/O and deadline handling; Claude/Codex UserPromptSubmit, Stop, SessionStart, Claude SessionEnd/PreCompact/opt-in PostToolUse; bounded server-owned memory-usage-audit dispatch after assistant ingestion; caller-surface tests; relevant roadmap/docs.

**Constraints:**
No public API or schema change; Relay remains first and fail-closed; never ACK context that was not flushed to the host; assistant ingestion succeeds independently of best-effort audit population; audit capacity is isolated from Relay/diagnostics; no real sleeps in the standard suite; preserve Windows/Linux/macOS behavior and package boundaries.

**Completion criteria:**
Every installed Python hook observes one monotonic total budget and bounds or explicitly skips blocking work by remaining time; Relay output is UTF-8 and flushed before ACK with safe lease recovery when completion budget is unavailable; Stop performs no synchronous audit fan-out; every durable assistant ingest can enqueue bounded audit population even without a semantic package; failed/dropped audit work leaves idempotent pending rows for retry on a later assistant ingest; deterministic caller-surface tests cover slow/unavailable services, interruption, retry, optional-work skipping, queue saturation/shutdown, and mixed load.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies core/service.py as a red-zone orchestrator requiring architecture review; integration hooks are unclassified/gray. Moderate complexity spans two runtimes, lifecycle ordering, bounded asynchronous work, and caller-surface E2E without changing public contracts.

**Discovery:**
The host timeout is an aggregate-budget defect: individually bounded Git/HTTP calls can exceed Claude's 8s/15s hook limits. Claude and Codex Stop duplicate a best-effort usage-audit loop that lists up to 20 rows and performs an expand plus update per row. Relay is emitted before ACK but host streams are not explicitly flushed. PR #129 already removed disabled PostToolUse launches, added session identity/work-ref caching, and fast-abstains semantic-unavailable prompt queries; this task must not repeat those changes. The existing source-item processor cannot own audit matching when no semantic package is active because ingest marks the item completed and no claim occurs. Audit matching is pure but incorrectly owned by the Claude integration. A bounded standard-library executor at the HTTP ingestion boundary can enqueue after durable ingest, isolate one worker and a finite backlog, cancel queued jobs and drain the active job before storage shutdown, and leave rows pending on failure.

**Material assumptions:**
A one-worker bounded standard-library executor is sufficient because audit data is best-effort telemetry and each job is capped to the existing 20 pending rows; saturation or process failure leaves rows pending, and the next assistant ingest retries them. If one bounded job cannot finish promptly without external I/O, optimize or cap the pure matcher before allowing shutdown to wait. Host stdin and stream writes cannot be forcibly timed out portably; bound accepted input size, check the monotonic budget immediately before output, flush synchronously, and ACK only after successful flush while the one-second host reserve remains.

**Plan:**
1. Move the pure matcher to a core-owned module. Add a service method that reads at most 20 pending rows, builds canonical match text from stored memories, classifies the supplied assistant text, and uses the existing idempotent update; isolate each row failure.
2. At the /items boundary, after each assistant item is durably ingested, submit thread plus bounded response text to a dedicated one-worker executor guarded by a nonblocking finite semaphore. Queue saturation/failure drops only the job, not ingestion; pending rows retry on a later assistant ingest. Start ownership with app construction and cancel queued/drain active work before storage closes.
3. Remove both Stop-local matcher/fetch/population loops. Stop keeps Relay handling and required assistant ingestion only.
4. Add one monotonic deadline per hook process in each standalone common module. Clamp every HTTP, Relay ACK, credential, and Git subprocess timeout to remaining budget; bound hook input/transcript reads; make state lock retry respect the deadline; skip optional work when no safe budget remains. Cover UserPromptSubmit, Stop, SessionStart, SessionEnd, PreCompact, and enabled PostToolUse.
5. Emit exact UTF-8 Relay/context output, flush the actual stream, then ACK only while the internal budget remains. Never reset the deadline per operation; leave unacknowledged deliveries for lease recovery.
6. Add deterministic caller-surface coverage for budget boundaries, slow/unavailable operations, flush/ACK order and interruption, async audit success/failure/idempotence/no-semantic path, executor saturation/shutdown, later-turn retry, and mixed Relay/diagnostic/audit load. Use fake clocks/events, never wall-clock sleeps.
7. Align roadmap/docs, run focused then full cross-platform-safe verification, obtain result review, open PR, resolve review threads/CI, merge, reinstall integrations from main, and restart via scripts/restart-service.ps1.

**Verification plan:**
When blocking work consumes the budget, each installed hook shall exit before its configured host timeout and skip only optional work → deterministic hook entry-point tests with fake clock and bounded request/subprocess assertions.
When Relay context is delivered, the hook shall flush exact UTF-8 output before ACK; interruption or insufficient completion budget shall leave it recoverable → caller-surface emit/ACK ordering and expired-lease redelivery E2E.
When an assistant item is durably ingested with or without an active semantic package, the request shall return independently and bounded audit work shall populate pending rows once → full HTTP lifecycle E2E including executor saturation, failure, later-ingest retry, and idempotence.
When the service shuts down, queued audit jobs shall be cancelled and active work shall finish before storage closes → deterministic lifecycle test with events and no sleep.
When SessionStart, PreCompact, or PostToolUse lacks remaining time, optional queries shall not start → entry-point tests across zero/boundary/available budgets.
When prompt, Stop, audit, Relay, and diagnostics overlap, Relay admission and hook completion shall remain responsive → deterministic mixed-load E2E with independent capacity.
All supported runtime paths shall remain portable → focused Claude/Codex/OpenCode compatibility suites plus Linux/Windows CI.

**Plan review:**
Clean-context review /root/pr2_plan_review; blocking findings incorporated in the revised plan and Plan review section below.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-07: Established scope from the user-approved two-PR performance plan and recovered the prior Claude architecture review. PR #129 is merged; this branch starts from main 9ccdcccd.
- 2026-09-07: Pre-edit redline review reported a red-zone orchestrator touch (core/service.py), no boundary violation, and minimum Elevated risk.
- 2026-09-07: Discovery disproved reuse of the semantic source-item worker for all audit work because no-package assistant items are never claimed. Revised the plan to a bounded post-ingest executor with explicit lifecycle and pending-row retry semantics.
- 2026-09-07: Implemented the correction pass: queueing carries only the durable source-item ID; the worker loads the persisted assistant item and skips missing, non-assistant, or empty rows; the hook compatibility import resolves the checkout root temporarily. Focused tests cover source-ID dispatch and saturation.
- 2026-09-07: The original server-owned slice remains in commit 22521477: core matcher relocation, bounded executor, per-row population, assistant `/items` enqueue, and shutdown drain.
- 2026-09-07: Added the shared monotonic deadline primitive to both standalone hook common modules; Pallium/Relay HTTP and aggregate ACK calls clamp to the same remaining budget and skip network work when exhausted. A cheaper delegated attempt was interrupted after correctness review found undefined deadline variables and an unbounded timeout=None path; the parent repaired the minimal slice.
- 2026-09-07: Completed whole-hook budgets across all nine installed Python entry points, bounded stdin/transcript parsing, Git, state-lock, credential, Pallium, Relay, and ACK work, and added exact UTF-8 flush-before-ACK behavior. Removed both synchronous Stop audit loops and their compatibility wrapper; Stop now performs Relay plus one durable assistant ingest only.
- 2026-09-07: `apply_patch` was attempted once and failed with the machine-local CreateProcessWithLogonW restriction. Subsequent edits used exact, named-file deterministic replacements. A delegated test edit corrupted one test file without committing; the parent restored that file from HEAD, reapplied the three known local assertions, and verified the full focused suite.

## Evidence

- Historical plan lookup 6e66a3a4-25ba-596f-bd07-12cd33cd0f09.
- Pre-edit clean-context redline review /root/pr2_redline.
- Focused verification: 31 matcher/canonical-text tests and 2 deterministic audit-dispatch lifecycle tests passed.
- Final server-slice verification: 46 focused tests passed, including exact POST /items semantic-unavailable persistence, enqueue false/exception isolation, durable-ID dispatch, per-row failure isolation, and matcher regressions; matcher now indexes fixed-width response windows.
- Deadline primitive verification: tests/test_agent_relay_hooks.py - 42 passed; fake clocks prove clamping, exhaustion skips urlopen, and multi-delivery ACK stops on the shared budget.
- Final focused PR2 verification: 200 passed, 1 skipped in 9.87s across deadline/flush, Relay hooks, audit dispatch, Claude/Codex integration, structural work refs, wake registration, canonical matcher, and Phase 5b match-text coverage; no real sleeps were added.
- Hook parity verification: 110 passed. Opt-in PostToolUse verification: 19 passed. Dedicated deadline-safety file: 14 passed in 4.06s.
- Server lifecycle regressions verify source-miss retry on later assistant ingest and active audit drain before storage-close progression using events rather than wall-clock sleeps.
- Clean-context plan review /root/pr2_plan_review.

## Plan review

The reviewer found four blocking gaps: semantic processing cannot cover the no-package path; core must not import the integration-owned matcher; in-memory dispatch must state its recovery ceiling; and audit capacity/shutdown must be isolated. The revised plan moves the matcher into core, submits after durable HTTP ingestion regardless of package availability, bounds a dedicated one-worker executor and backlog, cancels queued work and drains active work before storage close, and defines pending-row retry on a later assistant ingest. It also expands deadline coverage to input/file/lock/output boundaries, clamps all HTTP/subprocess/ACK work to one monotonic budget, and requires flush before ACK. No public API, schema, or new dependency is introduced.

## Result review

Pending.