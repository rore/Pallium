# Retained authenticated restart admission recovery

<!-- agent-workflow:start -->
**Outcome:** Previously accepted authenticated Codex workers recover after service replacement and resolved temporary busy admission without requiring another recipient turn.
**Target:** Pallium.
**Scope:** app/mcp/codex_desktop_bridge.py, tests/test_codex_worker_reconnect.py, tests/test_codex_retained_wake.py, docs/codex-integration.md, and this Work Record.
**Constraints:** No live environment changes; no tool/message replay; preserve identity, continuity, capability, epoch, unresolved-I/O, shutdown and native submission fences; no automatic initial enrollment without an actual runtime request; no new connection architecture.
**Completion criteria:** Accepted worker survives transient busy after API replacement and existing pending delivery progresses without another MCP call; fresh Desktop/MCP actual requests enroll after service replacement in either restart order; uncertain responses, changed identities and unresolved disposal stop recovery; retries are bounded and never duplicate native submission.
**Requirement baseline:**
{"source":"manager-chat:01a0d7ce-83c6-77e2-90f7-d413894059e1/2026-10-11-restart-recovery-assignment","outcome":"Previously accepted authenticated Codex workers recover after service replacement and resolved temporary busy admission without requiring another recipient turn.","scope":"app/mcp/codex_desktop_bridge.py, tests/test_codex_worker_reconnect.py, tests/test_codex_retained_wake.py, docs/codex-integration.md, and this Work Record.","constraints":"No live environment changes; no tool/message replay; preserve identity, continuity, capability, epoch, unresolved-I/O, shutdown and native submission fences; no automatic initial enrollment without an actual runtime request; no new connection architecture.","completion_criteria":"Accepted worker survives transient busy after API replacement and existing pending delivery progresses without another MCP call; fresh Desktop/MCP actual requests enroll after service replacement in either restart order; uncertain responses, changed identities and unresolved disposal stop recovery; retries are bounded and never duplicate native submission."}
**Risk:** Elevated
**Complexity:** Moderate
**Reason:** Runtime lifecycle file is gray/watch; tests, docs and bookkeeping are blue. Narrow typed busy retry changes availability, not authorization or public API; independent technical review required.
**Discovery:** Main and installed revision 6be22d77. Historical delivery remained pending with attempts=0 after API restart; server enrollment was never_registered. All relevant Relay tools invoke registration. Existing busy-auto-reconnect test deliberately stops after a resolved busy reply; 11 existing focused cases pass. Historical client-side cause remains unknown. Native transports in fixtures are simulated; real MCP protocol, HTTP persistence and hook surfaces can be exercised in isolation.
**Material assumptions:** Typed busy means rejected admission with no uncertain write; verify against RetainedService registration and unresolved client disposal before retry, otherwise return to planning. The server never_registered observation does not identify the original client failure; do not claim this correction explains that incident. Manager owns full-suite and installed qualification integration; leave those gates explicitly open at handoff.
**Plan:** First create this Work Record and classify risk before code edits. Obtain clean-context plan review. Add failing recovery regressions through existing MCP/HTTP fixtures. Extend only _auto_reconnect's existing bounded backoff to retry typed busy after resolved disposal, same continuity and capability; leave every uncertain or nonbusy response terminal. Keep initial enrollment request-driven. Cover restart ordering, proof rejection, shutdown/deadline/exhaustion and no replay/duplicate submission. Run focused serial isolated checks and test selector; obtain smart independent result review and send revision/evidence to manager. Stop/replan on broader production surface or violated assumption.
**Verification plan:**
Accepted worker transient busy recovery -> actual FastMCP regression plus existing pending HTTP delivery/native-fake hook journey, red before fix and green afterward.
Fresh Desktop/MCP enrollment in both restart orders -> actual MCP request lifecycle tests with replaced worker/service fixture.
Identity, continuity, uncertainty and unresolved disposal exclusion -> reconnect/continuity existing cases and narrow busy rejection matrix.
Bounded retries and shutdown without duplicate submission -> attempt/window/cancellation matrix and HTTP status/submission counts.
Whole-change validation -> scripts/test-plan.py --base origin/main and Agent Workflow local check; manager owns full non-slow suite and required CI before merge.
**Plan review:** Agent technical review: /root/retained_busy_plan_review at 3b9781eb, approved with clarification: typed unavailable/busy at both ready and register, resolved _finish and _restart_allowed before shared backoff, same proof/capability, and actual RetainedService admission plus pending HTTP delivery/hook progression rather than count-only evidence.
**Approvals:** Not required at this risk level. User authorizes isolated fixes and manager delegation; live environment changes are not authorized.
**Exceptions:** —
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

2026-10-11: Isolated feat/retained-busy-recovery based on 6be22d77fc059d687563433f94b2523cc90686c0. Only target classes/functions: InventoryWorker._auto_reconnect and relevant reconnect/retained HTTP tests. No production or test edits before plan review. Blocked only on that technical checkpoint.

Plan checkpoint: independent reviewer approved retrying ready/register explicit busy with resolved disposal and unchanged continuity, within the existing loop. HTTP regression must replace the fixture's pre-admitted service so it proves restored admission. No protected behavior-contract files change; the ordinary busy-stop test is intentionally replaced by the requested automatic recovery expectation. No API, schema, exports, config or callers need modification; _recover_if_gone is the sole production caller.

## Evidence

Pre-existing isolated baseline: 11 focused cases passed, native transport simulated. Not a failing reproduction and not installed recovery qualification.

## Result review

Not yet performed. Full-suite, CI, PR/merge and installed-host acceptance remain open under manager ownership.
