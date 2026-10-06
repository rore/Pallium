<!-- agent-workflow:start -->
**Outcome:** Eligible Relay recipients recover pending messages across missed notifications, unacknowledged claims, and recoverable native-host failures, with usable delivery diagnostics and evidence that distinguishes simulated delivery from installed model receipt.

**Target:** Pallium Relay recovery and Codex integration.

**Scope:** Existing Codex hook claim and wake-reservation recovery, retained Desktop transport failure handling and bounded diagnostics, Relay trace MCP scope handling, related caller-surface tests, installed dedicated-session qualification, and canonical Relay roadmap/deployment records. No broad transport or scheduler redesign.

**Constraints:** Preserve active-claim exclusion, exact endpoint/scope/generation ownership, successful-ACK terminal state, authenticated native custody, stale-worker exclusion, and bounded nonconcurrent notification retry. Never weaken protected behavior contracts merely to restore green. Preserve active user sessions and user data; use isolated test sessions and databases for fault injection. Do not upgrade the shared Claude CLI. Manual recipient turns or receive fallbacks do not count as automatic recovery. Keep unexplained historical incidents unresolved.

**Completion criteria:** Expired unacknowledged SessionStart claims can recover automatically and do not permanently block later messages, including after scope move; active claims remain excluded and committed ACKs remain delivered even if their response is lost. Empty-wake exact-delivery tracing works through its supported trusted MCP surface when hook scope is absent. Reproducible native connection failure has bounded diagnostics and a reviewed safe recovery outcome. Caller-surface regressions, affected suites, whole-change checks, independent reviews, PR CI, merge and installed-service synchronization pass. Dedicated installed native-host journeys track the same delivery through retry, claim, emission, ACK and payload-specific model response, including restart and backlog; any unverified journey remains explicitly open rather than being represented as qualified.

**Requirement baseline:**
{"source":"user:2026-10-06 then own this round","outcome":"Eligible Relay recipients recover pending messages across missed notifications, unacknowledged claims, and recoverable native-host failures, with usable delivery diagnostics and evidence that distinguishes simulated delivery from installed model receipt.","scope":"Existing Codex hook claim and wake-reservation recovery, retained Desktop transport failure handling and bounded diagnostics, Relay trace MCP scope handling, related caller-surface tests, installed dedicated-session qualification, and canonical Relay roadmap/deployment records. No broad transport or scheduler redesign.","constraints":"Preserve active-claim exclusion, exact endpoint/scope/generation ownership, successful-ACK terminal state, authenticated native custody, stale-worker exclusion, and bounded nonconcurrent notification retry. Never weaken protected behavior contracts merely to restore green. Preserve active user sessions and user data; use isolated test sessions and databases for fault injection. Do not upgrade the shared Claude CLI. Manual recipient turns or receive fallbacks do not count as automatic recovery. Keep unexplained historical incidents unresolved.","completion_criteria":"Expired unacknowledged SessionStart claims can recover automatically and do not permanently block later messages, including after scope move; active claims remain excluded and committed ACKs remain delivered even if their response is lost. Empty-wake exact-delivery tracing works through its supported trusted MCP surface when hook scope is absent. Reproducible native connection failure has bounded diagnostics and a reviewed safe recovery outcome. Caller-surface regressions, affected suites, whole-change checks, independent reviews, PR CI, merge and installed-service synchronization pass. Dedicated installed native-host journeys track the same delivery through retry, claim, emission, ACK and payload-specific model response, including restart and backlog; any unverified journey remains explicitly open rather than being represented as qualified."}

**Risk:** High

**Complexity:** Large

**Reason:** Persisted Relay lifecycle and caller-facing MCP paths are red-zone persistence/API surfaces; native custody is security-sensitive. Several independently verifiable recovery boundaries and installed qualification require coordinated ownership.

**Discovery:** Read-only review on installed dbb699f4 reproduced accepted wake reservation plus uncorrelated committed claim/no ACK, expired lease, reconciliation returning no action and refusal to reserve a later message; repeated after exact endpoint scope move. Correlated expired claims replace the reservation; active claims are excluded; successful ACK releases it. SessionStart does not supply wake_delivery_id, while server correlation and expired-claim replacement require wake correlation. PR284 covers never-claimed missed notifications but explicitly lacks a new installed lost-notification witness. Manager separately reports unnecessary MCP trace scope requirement and native response failure deleting retained registration; its exact evidence and current ownership are requested before implementation.

**Material assumptions:** Existing SQLite fence and claim metadata can support safe recovery without a second scheduler or schema; disprove through caller-surface race testing and return to planning. A retained-host failure can be classified without logging private response, endpoint or credentials; if original failure cannot be established, retain safeguards and keep incident open. Dedicated native test sessions can witness automatic recovery without disturbing active chats; if capability or host is unavailable, record the exact blocker and do not substitute manual activation. Manager can transfer roadmap coordination cleanly; until confirmed, do not mutate shared roadmap files.

**Plan:** First invoke the agent-workflow skill to create this Work Record and classify risk before any code edit. Reconcile exact manager evidence and current work; inspect all claim/reconcile and retained-transport callers. Obtain clean-context technical plan review before source edits. Split only independently testable, nonoverlapping fixes into bounded cheaper-agent assignments; main agent owns security/persistence judgment and installed acceptance, and a smart nonimplementer reviews results. Reuse existing recovery, custody and diagnostic machinery. Run narrow failing caller-surface reproductions, implement the smallest correct shared fixes, preserve successful-ACK and active-claim controls, then combine affected checks and one selector-required full suite. Obtain independent combined review, address PR comments and CI, merge under standing approval, sync both stable checkouts and restart through the installed wrapper. Qualify dedicated native-host journeys with payload-specific replies; update canonical roadmap with exact simulated/live evidence and unresolved incidents. Archive completed worktrees only after installation references and evidence are safe.

**Verification plan:**
When an uncorrelated SessionStart claim expires without ACK, recovery admits the original and later delivery without a manual turn, including scope move -> real hook/HTTP/SQLite failure-and-recovery regression with native transport simulated, then a separate installed-host qualification.
When claim response is lost, ACK fails before commit, or committed ACK response is lost -> separate caller-surface tests preserving active lease and terminal ACK behavior, generation races, restart and later backlog.
When an exact empty-wake trace lacks injected scope -> supported trusted MCP call succeeds without guessed scope; invalid IDs, unknown delivery, trust boundaries and ordinary scoped calls remain correct.
When retained native response/custody fails -> bounded sanitized error category and reviewed authenticated recovery; simulated faults and installed observations reported separately.
When combined changes are ready -> independent smart plan/result reviews, whole-change test selector, required full non-slow suite, import boundaries, Redline, workflow, fresh PR CI/review and installed health/status/queue/embedding verification.
When dedicated installed test recipient receives a recovered payload -> same delivery ID linked to native attempt/retry, real hook emission/ACK and a payload-specific model response; no manual-turn/receive substitute.

**Plan review:** Pending clean-context technical review after manager evidence and scope reconciliation.

**Approvals:** Approved by user 2026-10-06: "then own this round". Standing authorization: "you can push pr and merge if all is ok", "i approve for you what you need", and "i approve what is needed". User also authorized budget-conscious delegated implementation and smart reviews; no repeated confirmation for the already-authorized round.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

Invoked Agent Workflow before any implementation edit. Normal workflow applies: intended hook, storage, MCP and transport application paths are outside the documentation allowlist and include red-zone persisted/API behavior; no exemption is claimed. This isolated managed checkout is on feat/relay-recovery-round. Initial source remains unchanged. Manager coordination request relay-msg-3d3d1b345cd84e0ebf8fec06851c646c is saved but unclaimed with native_unavailable; authorized app fallback requested current work/evidence and shared-roadmap handoff without model/effort overrides. The state is planning pending that reconciliation and independent technical review, not an approval request.

Canonical feature reference: roadmap/features/add-wake-first-relay-delivery.md. Shared roadmap owner/checkout transfer is pending manager confirmation; do not change shared roadmap yet.

## Evidence

Prior read-only temporary-database diagnostic on installed dbb699f4: six cases (uncorrelated/correlated/ACK, before/after scope move). Uncorrelated expired claims keep accepted fence and block later reservation. Correlated expired claims replace it; ACK releases it; active claims exclude recovery. This is storage-level reproduction, not a full installed Desktop journey or proof of historical cause.

## Result review

Pending.

