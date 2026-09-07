# Hook deadline and audit-backlog safety

<!-- agent-workflow:start -->
**Outcome:**
Claude Code and Codex hooks finish within their host budgets without losing delivered Relay context, and assistant ingestion no longer waits on usage-audit fan-out.

**Target:**
Pallium hook integrations and the existing server ingestion/processing path.

**Scope:**
Shared Python hook I/O and deadline handling; Claude/Codex UserPromptSubmit, Stop, SessionStart, Claude SessionEnd/PreCompact; server-owned memory-usage-audit population after assistant ingestion; caller-surface tests; relevant roadmap/docs.

**Constraints:**
No public API or schema change; Relay remains first and fail-closed; never ACK context that was not durably emitted; assistant ingestion succeeds independently of best-effort audit population; no real sleeps in the standard suite; preserve cross-platform Windows/Linux/macOS behavior and existing package boundaries.

**Completion criteria:**
Every Python hook observes one monotonic total budget and bounds each blocking operation by the remaining time; Relay output is UTF-8 and flushed before ACK with safe lease recovery when completion budget is unavailable; Stop performs no synchronous audit fan-out; existing audit verdicts are populated asynchronously and idempotently after assistant ingestion; deterministic caller-surface tests cover slow/unavailable services, interruption, expiry recovery, optional-work skipping, and mixed load.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies core/service.py as a red-zone orchestrator requiring architecture review; integration hooks are unclassified/gray. Moderate complexity spans two runtimes, lifecycle ordering, asynchronous server work, and caller-surface E2E without changing public contracts.

**Discovery:**
The host timeout is an aggregate-budget defect: individually bounded Git/HTTP calls can exceed Claude's 8s/15s hook limits. Claude and Codex Stop duplicate a best-effort usage-audit loop that lists up to 20 rows and performs an expand plus update per row. Relay is emitted before ACK but Claude output is not explicitly flushed. PR #129 already removed disabled PostToolUse launches, added session identity/work-ref caching, and fast-abstains semantic-unavailable prompt queries; this task must not repeat those changes. The repository already has asynchronous source-item processing and idempotent usage-audit update contracts to reuse. Redline found no boundary violation or API/schema/security/persistence surface.

**Material assumptions:**
The usage-audit matcher can run from the existing server processing lifecycle using already stored assistant content and pending audit rows; disproof is that required matching input exists only in hook-local state, which returns this task to planning. One shared deadline helper per integration can bound existing calls without changing hook host configuration; disproof is a host surface that cannot accept dynamic timeouts, which narrows that operation to an explicit skip rule. Emission can be flushed before ACK on supported stdout/stderr streams; disproof requires leaving the delivery unacknowledged for lease recovery.

**Plan:**
1. Trace all hook blocking calls and the existing post-ingestion processing lifecycle; identify one shared monotonic remaining-budget primitive per integration, reusing existing request helpers.
2. Add deadline propagation at the shared subprocess/HTTP boundary, then order each hook as required work first and optional enrichment only while budget remains. Relay delivery emits UTF-8, flushes, and ACKs only after successful emission with reserved completion time.
3. Remove both Stop-local usage-audit loops and invoke the shared matcher through the existing asynchronous server processing path after assistant ingestion, preserving idempotence and failure isolation.
4. Add deterministic caller-surface coverage for every hook budget, slow/unavailable operations, Relay emit/flush/ACK interruption and lease recovery, asynchronous audit success/failure/idempotence, SessionStart/PreCompact optional skipping, and mixed load. Use fake monotonic clocks/events, never wall-clock sleeps.
5. Align roadmap/docs, run focused then full cross-platform-safe verification, obtain result review, open PR, resolve review threads/CI, merge, reinstall integrations from main, and restart via scripts/restart-service.ps1 only if server code changed.

**Verification plan:**
When blocking work consumes the budget, each installed hook shall exit before its configured host timeout and skip only optional work → deterministic hook entry-point tests with fake clock and bounded request/subprocess assertions.
When Relay context is delivered, the hook shall flush exact UTF-8 output before ACK; interruption or insufficient completion budget shall leave it recoverable → caller-surface emit/ACK ordering and expired-lease redelivery E2E.
When an assistant item is ingested, Stop shall return without audit HTTP fan-out and server processing shall populate pending rows once → full HTTP/hook lifecycle E2E including delayed/failing/idempotent audit processing.
When SessionStart or PreCompact lacks remaining time, orientation or the second query shall not start → entry-point tests across zero/boundary/available budgets.
When prompt, Stop, and background processing overlap, Relay admission and hook completion shall remain responsive → deterministic mixed-load E2E with no real sleeps.
All supported runtime paths shall remain portable → focused Claude/Codex/OpenCode compatibility suites plus Linux/Windows CI.

**Plan review:**
Pending clean-context review.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- 2026-09-07: Established scope from the user-approved two-PR performance plan and recovered the prior Claude architecture review. PR #129 is merged; this branch starts from main 9ccdcccd.
- 2026-09-07: Pre-edit redline review reported a red-zone orchestrator touch (core/service.py), no boundary violation, and minimum Elevated risk. Implementation remains blocked pending focused discovery and clean-context plan review.

## Evidence

- Historical plan lookup 6e66a3a4-25ba-596f-bd07-12cd33cd0f09.
- Pre-edit clean-context redline review /root/pr2_redline.

## Result review

Pending.