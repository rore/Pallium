# Retained registration emergency repair

<!-- agent-workflow:start -->
**Outcome:**
Restore automatic Relay availability after a safely resolved retained-client registration transport failure.

**Target:**
Pallium Codex retained client.

**Scope:**
app/mcp/codex_desktop_bridge.py and focused retained-worker caller-surface regression tests; existing bounded diagnostics only if needed to distinguish terminal registration failure.

**Constraints:**
Preserve authenticated source, thread, capability, service and continuity checks; unresolved I/O and unknown identity remain fenced; never replay the failed caller or message; isolate tests and preserve everyday installation and data.

**Completion criteria:**
A resolved typed foreground transport/deadline failure followed by a valid unchanged authenticated channel keeps wake recovery alive without replay; rejection, identity change and unresolved I/O remain fenced. Local installation changes require separately described explicit approval and actual delivery verification.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Restore automatic Relay availability after a safely resolved retained-client registration transport failure.","scope":"app/mcp/codex_desktop_bridge.py and focused retained-worker caller-surface regression tests; existing bounded diagnostics only if needed to distinguish terminal registration failure.","constraints":"Preserve authenticated source, thread, capability, service and continuity checks; unresolved I/O and unknown identity remain fenced; never replay the failed caller or message; isolate tests and preserve everyday installation and data.","completion_criteria":"A resolved typed foreground transport/deadline failure followed by a valid unchanged authenticated channel keeps wake recovery alive without replay; rejection, identity change and unresolved I/O remain fenced. Local installation changes require separately described explicit approval and actual delivery verification."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Runtime path is gray/watch under Redline; bounded worker lifecycle change preserves existing admission/security contracts. Actual first failure category remains unknown.

**Discovery:**
Installed16440107 already contains ff8d982/bdacab61/cc6c561 recovery. Client66600 stopped at2026-10-26T12:47:04.696540Z with reregister-unavailable; service IO232 followed while source stayed alive. Worker may discard a healthy checked source after nonbusy foreground failure. No claim/ACK for hello delivery relay-delivery-3450aefd216f450a9803271bb6c841b0. Original registration error was not recorded.

**Material assumptions:**
Hypothesis is limited to a resolved typed failure plus healthy follow-up; disprove with caller-surface reproducer before fixing. Unknown/refused/uncertain results must still fence. If actual source invalidates this hypothesis, update plan before editing production. Current main base9a1addd2 differs from installed16440107; compare relevant source before rollout.

**Plan:**
Use existing InventoryWorker and protocol fixtures. First add a regression proving resolved typed transport/deadline failure followed by unchanged healthy ready must not lose retained wake worker. Preserve busy handling and existing refusal/uncertain cases. Keep only the validated original channel and metadata, never retry the failed caller. Add bounded category-only diagnostic attribution if required for unclassified terminal outcomes. No new recovery subsystem, API, dependencies, settings or service changes. Stop/replan if checks cannot prove existing authority remains safe.

**Verification plan:**
Healthy resolved failure and no replay -> actual MCP worker regression plus exact registrations/tool-operation counts and worker liveness.
Identity/refusal/uncertainty preservation -> existing and added worker negative matrix plus retained-connection recovery tests.
Whole change -> scripts/test-plan.py --base origin/main, selected required checks and one full non-slow suite, clean-context result review, required CI.
Local repair -> separately approved exact installed update/reconnection scope, health and same pending delivery through payload-specific recipient response; simulated tests are not installed acceptance.

**Plan review:**
Agent technical review: /root/reregister_plan_review, 2026-10-26. GO for retaining only the same checked client after a resolved typed transport/deadline failure; exact sequence/epoch authentication on follow-up ready rejects stale replies. Preserve generic/refused/invalid-primary fences even when follow-up ready is healthy. Existing no-replay/identity/I/O requirements preserved.

**Approvals:**
Ordinary isolated bugfix/PR/merge authorized by user; no new live-environment approval inferred. Not required at this risk level.

**Exceptions:**
—

**State:**
Ready for review
<!-- agent-workflow:end -->

## Implementation

2026-10-26: User declared local Relay code red and requested minimal safe bugfix/process overhead. Manager confirmed no overlapping owner through authorized app fallback because native wakes are unavailable. New managed isolated checkout from origin/main9a1addd2; branch feat/retained-reregister-repair. Intended files: app/mcp/codex_desktop_bridge.py; tests/test_codex_worker_reconnect.py and tests/test_codex_retained_connection_recovery.py if actual-caller coverage requires it. No protected tests, live installs or service changes authorized by this record. Source routing remains with manager; no exact canonical roadmap reference supplied, keep linkage unverified rather than inventing it.

## Evidence

Plan review accepted before test edits. Emergency instruction relayed by manager: quick focused iterations, no extra agents/repeated reviews/broad unrelated suites; existing review completes. Focused regression and subsystem checks take priority; hosted required CI remains a merge gate.

Pre-fix actual MCP regression transport-failed-healthy failed with unavailable/stopped on the next caller. Production fix changes only the existing same-client continuation condition for typed transport/deadline failures after successful authenticated recovery. Other primary failures still stop the worker; fresh-caller restart behavior is unchanged. Added actual NativeInventoryClient/RetainedService protocol journeys simulate a lost foreground registration response, then verify later idle re-enrollment without another caller, preserving original admitted metadata and exact operation counts. These three protocol journeys passed. Two affected-file serial run is in progress in task-private PALLIUM_HOME with live URL disabled. No production diagnostics, protocol or protected-test changes were needed.

Focused verification completed at application revision1bc66bbffd28819d6bb4956e1eedf277883f93c6: python -m pytest tests/test_codex_worker_reconnect.py tests/test_codex_retained_connection_recovery.py -q -n 0:217 passed in56.96s. Output build/emergency-focused.log. Existing shared dependencies were read without modification; PALLIUM_HOME task-private and base URL127.0.0.1:1. Selector reports full lane; local full-suite repetition deferred per human emergency instruction relayed by manager, required hosted CI remains a merge gate. Installed acceptance and original error category remain unresolved.

Diagnosis uses current source, installed ancestry, client close log and service source-close log. Original error category is unresolved; do not label the historical incident reproduced until a matching boundary is established.

## Result review

Agent technical review: /root/reregister_plan_review, clean-context non-implementer, 2026-10-26: GO; no blocking findings. Narrow condition matches plan. Refusal/invalid/generic-primary cases still stop; no failed metadata replacement or caller replay. Actual-protocol fixture proves processed registration with lost response then authenticated healthy readiness and later idle recovery using original admitted turn. Source inspection confirms exact epoch/sequence validation rejects stale registration responses; queued stale native response was not fault-injected.

Reviewed revision: 1bc66bbffd28819d6bb4956e1eedf277883f93c6.

Verification adequacy:217 focused tests passed; adequate for the bounded implementation and preserved safety checks. Simulated native transport does not establish installed Win32 cancellation/recovery or payload consumption; original incident attribution and installed acceptance remain open. Risk remains Elevated/Moderate. Local broader suite omitted under the explicit emergency instruction, required hosted checks still required before merge.

