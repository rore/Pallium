<!-- agent-workflow:start -->
**Outcome:** Ordinary Relay delivery uses the authenticated retained Codex MCP connection to wake its target and deliver payload through the existing hook and ACK path.

**Target:** Existing Codex MCP lifecycle, service wake scheduler, and SessionStart hook.

**Scope:** app/mcp/codex_desktop_bridge.py, app/mcp/server.py, app/codex_bridge_pipe.py, app/codex_wake.py, existing service startup and Codex integration setup, their focused tests, integrations/codex/hooks/session_start.py, docs/codex-integration.md, roadmap/features/add-wake-first-relay-delivery.md. Reuse existing durable reservations and hook primitives; no new persistence design.

**Constraints:** Simplify without losing functionality or quality. One retained-MCP wake path; no CLI/deep-link fallback, parallel scheduler, manual receive/ACK, fabricated caller, uncertain retry, secret logging, or changes to trust/settings. Keep existing spent trial fences. Report before and after concrete steps; ask before changing direction.

**Completion criteria:** Normal authenticated MCP activity supplies service wake custody without the trial operator procedure; disconnect/restart invalidates custody; one existing durable reservation authorizes at most one uncertain native write; unavailable connection leaves delivery pending; hook emits before ACK; focused caller-surface tests cover success and failure boundaries; docs distinguish proved behavior and limitations.

**Requirement baseline:** {"source":"user:f6f06468-5757-4d5b-9476-e150f891b9ee","outcome":"Ordinary Relay delivery uses the authenticated retained Codex MCP connection to wake its target and deliver payload through the existing hook and ACK path.","scope":"app/mcp/codex_desktop_bridge.py, app/mcp/server.py, app/codex_bridge_pipe.py, app/codex_wake.py, existing service startup and Codex integration setup, their focused tests, integrations/codex/hooks/session_start.py, docs/codex-integration.md, roadmap/features/add-wake-first-relay-delivery.md. Reuse existing durable reservations and hook primitives; no new persistence design.","constraints":"Simplify without losing functionality or quality. One retained-MCP wake path; no CLI/deep-link fallback, parallel scheduler, manual receive/ACK, fabricated caller, uncertain retry, secret logging, or changes to trust/settings. Keep existing spent trial fences. Report before and after concrete steps; ask before changing direction.","completion_criteria":"Normal authenticated MCP activity supplies service wake custody without the trial operator procedure; disconnect/restart invalidates custody; one existing durable reservation authorizes at most one uncertain native write; unavailable connection leaves delivery pending; hook emits before ACK; focused caller-surface tests cover success and failure boundaries; docs distinguish proved behavior and limitations."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Replaces the wake transport at an authenticated process/caller boundary. MCP API path is red; native custody is security-sensitive. No forbidden dependency or schema change is proposed.

**Discovery:** Ordinary scheduling already reserves and reconciles deliveries, but launches codex queue. The retained connection currently enters through a finite inventory registration with manual policy and trial files. The successful service-owned unloaded witness is build/codex-retained-session-start-witness-20261001-1225.json; it proves the mechanism once, not normal connection lifetime. Existing SessionStart hook/test changes are preserved. Roadmap still contains an obsolete claim that unloaded activation remains wholly unproved.

**Material assumptions:** Runtime-owned request metadata and same-user verified process ancestry can supply normal registration without model identity. Establish the precise authority and disconnect rules before edits. If this cannot reuse the current custody boundary, report the uncovered decision before changing direction.

**Plan:** Invoke agent-workflow and classify before code edits. Map normal registration and disconnect onto existing authenticated transport; obtain clean-context review of the concrete lifecycle. Replace the scheduler launch with the retained owner call using its existing durable reservation; reuse the hook patch. Remove trial-only control requirements from normal operation without resetting historical fences. Verify focused caller journeys and align documentation.

**Verification plan:** Registration with valid runtime metadata opens custody; missing/conflicting caller or invalid peer/descriptor performs no owner write. Disconnect, epoch change and expired authority invalidate custody. Concurrent sends/recovery retain one durable owner attempt; uncertain response never retries. Pending delivery with no connection stays pending. Existing SessionStart caller checks prove emit-before-ACK and failure handling. Run affected tests only during local iteration; preserve protected behavior contracts unchanged.

**Plan review:** Agent technical review: /root/retained_product_review, 2026-10-01, current HEAD fb94910c2ba5a1fae306532c8cf93d2b7e1a0516 plus preserved dirty hook prototype. Not GO for unconditional replacement: native send may join an active turn and has no atomic idle-only admission; connection origin does not confer standing cross-project destination authority. Existing primitives suffice once exact product behavior is decided. No production edit yet.

**Approvals:** Approved by user 2026-10-01: "ok, you can drive this" following the presented one-path integration plan. Earlier instruction: "let's do this faster. do quick fast iterations, without process or PRs or whatever. let's resolve this quickly without overhead or process or stupid infrastructurte". Scope is local product integration, not a new wake mechanism or publication.

**Exceptions:** —

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

2026-10-01: Existing hook prototype preserved. Created feat/codex-retained-wake-product from current main without discarding local work. Applicability is non-exempt: intended runtime/API/hook paths plus dirty tests and Work Record fall outside the documentation allowlist. Planning continues on connection ownership and lifetime; not blocked on user approval.

## Recovery

Independent review completed. Two uncovered decisions remain: whether opt-in automatic wake may cover Relay-registered Codex recipients from every sender runtime, and whether its native notice may join an already active turn. Canonical docs/designs/codex-mcp-desktop-bridge.md currently forbids implicit global grants and busy interruption. Approved-send-only grants would silently narrow cross-runtime functionality, so that alternative has not been implemented. Status checks cannot close the busy-state race. Root is asking the human for the exact product contract, not another approval of the already-proved trial. No source edits or tests were needed for this finding.

Implementation reuse confirmed: actual FastMCP request context; existing bounded worker/private pipe/process handles; scheduler reservation persisted uncertain before native write; no schema addition or second scheduler. Preflight absence leaves pending; disconnect/epoch/process loss invalidates custody. Preserve historical trial fences and existing hook patch.

Local iteration follows the user's focused-test/no-PR direction. This is not an exception to identity, boundary, or review requirements. No publication is part of this local iteration.

Next: finish the concrete custody lifecycle and independent plan review, then implement locally. No live gate or trial is active. Canonical roadmap: roadmap/features/add-wake-first-relay-delivery.md.
