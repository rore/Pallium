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

Implementation checkpoint: desired actual-MCP recovery failed in all four busy stage/count cases on unchanged production. Corrected HTTP diagnostics fixture (router-only app has no /status); both pending-delivery cases then failed specifically at replacement enrollment recovery. Production change extends the existing retry/backoff only to ready/register explicit busy after resolved disposal and unchanged proof. First GREEN passed 24 cases; one fixture checkpoint raced successful recovery, so the replacement becomes observable to the worker only after the initial HTTP never_registered witness. Bounded test-only delegation owns tests/test_codex_retained_wake.py; parent reviews and runs evidence.

Verification checkpoint: strengthen busy to real _process custody-lock rejection (bounded helper thread), not a synthetic response. Fresh restart-order tests initially asserted custody after cleanup; moved those witnesses into the live exercise. Parent reviewed every delegated edit. No new runtime API, dependency, setting or guard weakening. Skill-feedback triggers from wrong local command paths and test fixture mistakes are agent-owned, not upstream skill defects; no report filed.

## Evidence

Pre-existing isolated baseline: 11 focused cases passed, native transport simulated. Not a failing reproduction and not installed recovery qualification.

RED MCP: 4 failed in 4.99s, private evidence pallium-busy-8370788c20564b3daaf0085b5c4fd78b/proof.log. RED pending delivery: 2 failed in 7.81s at replacement enrollment, pallium-busy-ff033f062642440998a6b33b7ba0ff35/proof.log. Safety/budget baseline: 13 passed, 2 desired retry/backoff failures. First GREEN: 24 passed, 1 fixture ordering failure; not claimed as passing validation. Each run used private profiles/databases and existing network guard; no recorded violations.

Whole-change selector chooses full lane, command python -m pytest tests/ -x -q. Manager must run full validation and required CI against the integrated revision; focused evidence alone does not satisfy those gates.

Strengthened RED: replaced only _auto_reconnect inside the private pytest process with the baseline function from git show 6be22d77 (checkout unchanged); both real custody-lock pending-delivery journeys failed at replacement enrollment, 2 failed in 8.20s. Evidence: pallium-busy-a320e5b9970f449bb054ce8102214044/proof.log.

Affected serial run: test_codex_worker_reconnect.py, test_codex_retained_wake.py, test_codex_retained_continuity.py, test_codex_retained_connection_recovery.py, test_codex_mcp_desktop_bridge.py: 412 passed and 2 newly authored cleanup-witness failures in 108.21s, pallium-busy-741897e18eb24d2daa56c3c0a32d24c2/proof.log. After moving the witnesses before cleanup and strengthening real busy rejection, the 4 affected HTTP journeys passed in 4.20s, pallium-busy-d28624aa578e4f40ad4e682788764f90/proof.log. No production edits after the subsystem run; all other tests unchanged. No guard violations recorded. This is split focused evidence, not a single green full-suite run.

## Result review

Not yet performed. Full-suite, CI, PR/merge and installed-host acceptance remain open under manager ownership.
