<!-- agent-workflow:start -->
**Outcome:** Ordinary Relay delivery uses the authenticated retained Codex MCP connection to wake its target and deliver payload through the existing hook and ACK path.

**Target:** Existing Codex MCP lifecycle, service wake scheduler, and SessionStart hook.

**Scope:** app/mcp/codex_desktop_bridge.py, app/mcp/server.py, app/codex_bridge_pipe.py, app/codex_wake.py, existing service startup and Codex integration setup, their focused tests, integrations/codex/hooks/session_start.py, docs/codex-integration.md, docs/designs/codex-mcp-desktop-bridge.md, roadmap/features/add-wake-first-relay-delivery.md. Reuse existing durable reservations and hook primitives; no new persistence design.

**Constraints:** Simplify without losing functionality or quality. One existing scheduler selects the existing queue for confirmed loaded-idle recipients or retained MCP for confirmed unloaded recipients. Working, unknown and disconnected recipients defer. No fallback after either attempt, parallel scheduler, deep link, manual receive/ACK, fabricated caller, uncertain retry, secret logging, or changes to trust/settings. Keep existing spent trial fences. Report before and after concrete steps; ask before changing direction.

**Completion criteria:** Normal authenticated MCP activity supplies service wake custody without the trial operator procedure; disconnect/restart invalidates custody; one existing durable reservation authorizes at most one uncertain native write; unavailable connection leaves delivery pending; hook emits before ACK; focused caller-surface tests cover success and failure boundaries; docs distinguish proved behavior and limitations.

**Requirement baseline:** {"source":"user:f6f06468-5757-4d5b-9476-e150f891b9ee","outcome":"Ordinary Relay delivery uses the authenticated retained Codex MCP connection to wake its target and deliver payload through the existing hook and ACK path.","scope":"app/mcp/codex_desktop_bridge.py, app/mcp/server.py, app/codex_bridge_pipe.py, app/codex_wake.py, existing service startup and Codex integration setup, their focused tests, integrations/codex/hooks/session_start.py, docs/codex-integration.md, roadmap/features/add-wake-first-relay-delivery.md. Reuse existing durable reservations and hook primitives; no new persistence design.","constraints":"Simplify without losing functionality or quality. One retained-MCP wake path; no CLI/deep-link fallback, parallel scheduler, manual receive/ACK, fabricated caller, uncertain retry, secret logging, or changes to trust/settings. Keep existing spent trial fences. Report before and after concrete steps; ask before changing direction.","completion_criteria":"Normal authenticated MCP activity supplies service wake custody without the trial operator procedure; disconnect/restart invalidates custody; one existing durable reservation authorizes at most one uncertain native write; unavailable connection leaves delivery pending; hook emits before ACK; focused caller-surface tests cover success and failure boundaries; docs distinguish proved behavior and limitations."}

**Behavior changes:** [{"target": "task-context.scope", "classification": "equivalent", "before": "app/mcp/codex_desktop_bridge.py, app/mcp/server.py, app/codex_bridge_pipe.py, app/codex_wake.py, existing service startup and Codex integration setup, their focused tests, integrations/codex/hooks/session_start.py, docs/codex-integration.md, roadmap/features/add-wake-first-relay-delivery.md. Reuse existing durable reservations and hook primitives; no new persistence design.", "after": "app/mcp/codex_desktop_bridge.py, app/mcp/server.py, app/codex_bridge_pipe.py, app/codex_wake.py, existing service startup and Codex integration setup, their focused tests, integrations/codex/hooks/session_start.py, docs/codex-integration.md, docs/designs/codex-mcp-desktop-bridge.md, roadmap/features/add-wake-first-relay-delivery.md. Reuse existing durable reservations and hook primitives; no new persistence design.", "reason": "Align the canonical bridge design with the already approved integration behavior; no additional runtime behavior."}, {"target": "task-context.constraints", "classification": "requirement-change", "before": "Simplify without losing functionality or quality. One retained-MCP wake path; no CLI/deep-link fallback, parallel scheduler, manual receive/ACK, fabricated caller, uncertain retry, secret logging, or changes to trust/settings. Keep existing spent trial fences. Report before and after concrete steps; ask before changing direction.", "after": "Simplify without losing functionality or quality. One existing scheduler selects the existing queue for confirmed loaded-idle recipients or retained MCP for confirmed unloaded recipients. Working, unknown and disconnected recipients defer. No fallback after either attempt, parallel scheduler, deep link, manual receive/ACK, fabricated caller, uncertain retry, secret logging, or changes to trust/settings. Keep existing spent trial fences. Report before and after concrete steps; ask before changing direction.", "reason": "User approved state-based selection with ok on 2026-10-01 directly following the architecture recommendation and explicit approval question. Loaded-idle native wake can skip payload hooks; reuse existing queue for that state. No after-attempt fallback.", "impact": "Loaded-idle recipients use the existing queue instead of retained native send, so the prompt hook receives the payload. Unloaded recipients retain the proven native path.", "alternatives": "Retained-only can skip loaded-idle payload hooks; retained wake followed by queue would add a redundant second action.", "authority": {"scope": "task", "name": "task-owner"}, "approval": {"by": "user", "reference": "direct conversation 2026-10-01 following architecture recommendation", "verbatim": "ok"}}]

**Risk:** High

**Complexity:** Moderate

**Reason:** Replaces the wake transport at an authenticated process/caller boundary. MCP API path is red; native custody is security-sensitive. No forbidden dependency or schema change is proposed.

**Discovery:** Ordinary scheduling already reserves and reconciles deliveries, but launches codex queue. The retained connection currently enters through a finite inventory registration with manual policy and trial files. The successful service-owned unloaded witness is build/codex-retained-session-start-witness-20261001-1225.json; it proves the mechanism once, not normal connection lifetime. Existing SessionStart hook/test changes are preserved. Roadmap still contains an obsolete claim that unloaded activation remains wholly unproved.

**Material assumptions:** Runtime-owned request metadata and verified source/Desktop process identity supply normal registration without model identity. The user approved coverage of registered Codex recipients across sender runtimes and a fresh idle/notLoaded precheck with explicitly best-effort non-interruption. No atomic busy-safe host operation is assumed. Disconnect/restart revokes connection custody; uncertain owner calls never retry.

**Plan:** Invoke agent-workflow and classify before code edits. Reuse private pipe/framing/process checks for ordinary runtime-metadata registration, with no new model-facing tool. The service retains one authenticated source connection; disconnect/source/Desktop loss or epoch change invalidates it. Read exact target Desktop status, then select one transport before spending: existing queue for idle, retained owner call for notLoaded, existing recovery sweep for working or unknown. Persist the existing reservation uncertain before initiation; never fall back after an attempt. Release the registry lock before response waits. Re-enrollment after restart requires fresh genuine request metadata. Reuse hook delivery/ACK and historical fences; no new database table or scheduler. Verify both payload journeys and the accepted check/send race.

**Verification plan:**
- Invalid caller/peer/descriptor, wrong target, malformed/error/unknown state performs zero owner writes -> focused MCP/private-channel caller regressions.
- Working target defers and is reconsidered when idle without a second scheduler -> send/recovery caller journey using persisted Relay state.
- Disconnect, source/Desktop loss and restart invalidate custody -> lifecycle caller regressions and resource cleanup assertions.
- Concurrent sends/recovery and uncertain response retain one durable owner attempt; failed fence means zero calls -> SQLite reservation and scheduler caller regressions.
- Idle/unloaded exact target dispatches; unrelated scopes remain untouched -> exact-target positive/negative caller tests.
- Hook emits before ACK and failures do not falsely mark delivery -> preserve existing twelve SessionStart caller cases and add only new-path regressions.
- Transport boundaries, Unicode, callback failure and shutdown remain bounded -> focused affected test files; preserve protected behavior contracts.

**Plan review:** Agent technical review: /root/retained_product_review, 2026-10-01. Updated GO after recorded user decisions: explicit automatic-wake opt-in covers registered Codex endpoints across sender runtimes; real caller metadata remains provenance, not global inferred identity; source/Desktop/channel/epoch lifetime bounds custody. Serialize exact read_thread status and owner call. Only schemaVersion1, matching thread.id, kind=codex, hostId=local, idle/notLoaded can dispatch; all else defers. Persist uncertain inside run_if_current before the native write; failures perform zero writes. Release pre-spend deferrals for existing recovery. No ended-turn TTL or policy files in normal mode. No new table or scheduler.

**Approvals:** Approved by user 2026-10-01: "ok, you can drive this" following the presented one-path integration plan. Earlier instruction: "let's do this faster. do quick fast iterations, without process or PRs or whatever. let's resolve this quickly without overhead or process or stupid infrastructurte". Scope is local product integration, not a new wake mechanism or publication.

Approved by user 2026-10-01: "approve the first, explain more the second?" (source 9ee30019-96cf-4297-82a4-ddb8538a5d93): enabling automatic wake covers registered Codex Relay recipients including other sender runtimes.

Approved by user 2026-10-01: "ok, and can we do that?" (source 403386cf-9268-4169-8d0a-e0d12799313a), following explicit idle/unloaded wake, working defer, unknown/disconnected defer, and best-effort non-interruption with a stated check/send race. This does not authorize deliberately waking a known-working target.

Approved by user 2026-10-01: "ok", directly after the architect recommendation and explicit question to implement queue for loaded-idle, retained MCP for unloaded, and defer working/unknown. This supersedes the earlier retained-only transport constraint. No source item identifier was injected for this approval; none is fabricated.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Updated plan independently accepted. Implementing local ordinary registration, state-aware owner dispatch and disconnect invalidation; no live deployment or fresh trial yet.

User source 94b92391-b916-4add-89f3-abe1c8254560 explicitly requires defensive programming and proper regression tests. Verification above now maps each significant failure boundary to caller-visible assertions; bounded implementer has received the requirement. This reinforces existing correctness requirements without changing behavior or scope.

2026-10-01: Existing hook prototype preserved. Created feat/codex-retained-wake-product from current main without discarding local work. Applicability is non-exempt: intended runtime/API/hook paths plus dirty tests and Work Record fall outside the documentation allowlist. Planning continues on connection ownership and lifetime; not blocked on user approval.

## Recovery

Update: both product decisions are settled by the exact user turns recorded above. Read-only Desktop read_thread response confirmed schemaVersion=1, exact thread.id, kind=codex, hostId=local, status.type=notLoaded. Next is concrete lifecycle review and implementation, not another approval question. The prior unresolved-decision paragraph below is historical.

Independent review completed. Two uncovered decisions remain: whether opt-in automatic wake may cover Relay-registered Codex recipients from every sender runtime, and whether its native notice may join an already active turn. Canonical docs/designs/codex-mcp-desktop-bridge.md currently forbids implicit global grants and busy interruption. Approved-send-only grants would silently narrow cross-runtime functionality, so that alternative has not been implemented. Status checks cannot close the busy-state race. Root is asking the human for the exact product contract, not another approval of the already-proved trial. No source edits or tests were needed for this finding.

Implementation reuse confirmed: actual FastMCP request context; existing bounded worker/private pipe/process handles; scheduler reservation persisted uncertain before native write; no schema addition or second scheduler. Preflight absence leaves pending; disconnect/epoch/process loss invalidates custody. Preserve historical trial fences and existing hook patch.

Local iteration follows the user's focused-test/no-PR direction. This is not an exception to identity, boundary, or review requirements. No publication is part of this local iteration.

Next: finish the concrete custody lifecycle and independent plan review, then implement locally. No live gate or trial is active. Canonical roadmap: roadmap/features/add-wake-first-relay-delivery.md.

## Architecture decision — 2026-10-01

Independent architect /root/retained_product_review recommends one scheduler/reservation with mutually exclusive state-based transport selection. Installed native loaded-owner handling skips resume and supplies delegated tool output, so it does not guarantee either payload hook. Existing queue supplies the ordinary prompt hook; unloaded retained wake has a bounded SessionStart payload/ACK witness. Combined automatic lifecycle still needs validation. Preserve custody and framing reuse; no new activation API enum, transport, persistence or scheduler. Focused regressions must cover both payload/ACK journeys, working-to-idle recovery, invalid/disconnected zero-action, fresh-metadata restart re-enrollment, concurrent recovery, failed fencing, response loss, and natural hook delivery overtaking the scheduled wake.

Review finding: a global retained bootstrap could attach an MCP client configured for another service. Accepted minimal correction binds the private directory to the existing launcher-supplied PALLIUM_SERVICE_PORT; the child derives the same port from a strictly validated loopback HTTP PALLIUM_BASE_URL. Existing PID/creation/epoch verification remains authoritative. Missing, mismatched or remote configuration defers without native action. No network probe, new token, API schema or launcher mechanism.

## Local validation — 2026-10-01

Implementation complete locally; no installation, enablement, publication, PR, or new live delivery trial. Source/test manifest: build/codex-retained-wake-product-reviewed-files.json, SHA256 ae4ba49c16bf40c86bfe645bb853914b86330ba9c63812197704a5b043a3f508 on base c3d3c1f8416f4f9cded5c7f90307e1bbef667c9a.

- Final focused HTTP/MCP/hook regressions: 74 passed in 17.63 seconds. Actual UserPromptSubmit and SessionStart hooks emitted the Unicode payload before ACK; read-back showed delivered. Desktop transport is simulated in these tests.
- Existing affected lane: 556 passed and 4 hook failures in 155.80 seconds. The new test loader left a common-module alias behind. Restoring the exact prior module entry on every exit fixed isolation; ordered replay of new hook journeys followed by all four affected cases and the canonical prompt contract passed 9 in 10.95 seconds. No production code or existing assertions were weakened for that fix.
- Strict URL parser correction: 25 focused cases passed in 0.69 seconds; included in final 74-case run.
- Existing native pipe tests could not enter bodies under the checkout ACL. Exact hash-verified test and conftest copies ran under an isolated private scratch with current checkout imports and unchanged ACL validation: 260 passed, one transport failure. The exact unchanged failed node passed on rerun. Its original cause is unestablished; this is not a claim that the original run was entirely green. Logs: build/codex-retained-native-scratch.log and build/codex-retained-native-exact-rerun.log. Scratch removed after processes exited; hashes preserved in build/codex-retained-native-scratch.json.
- Import boundaries and git diff --check passed. The selector requested a full lane because tests changed; the explicit user quick-local/no-full-suite/no-PR instruction governs this iteration. No full-suite result is claimed.

Source-level findings resolved: one state-selected transport before durable spending; registry lock released for hook callbacks; queue waits release connection custody; fresh runtime metadata required after reconnect; natural-hook delivery rechecked before spending; strict service-port binding; optional shutdown failure isolation; existing API enum retained without false qualification.

Activation remains explicit on both sides: Codex setup --automatic-wake and service PALLIUM_CODEX_AUTOMATIC_WAKE=1. The normal service launcher supplies its actual PALLIUM_SERVICE_PORT. No live settings were changed. Earlier finite native unloaded evidence remains valid; normal automatic combined lifecycle has not been live-qualified.

## Result review

Agent technical review: /root/retained_product_review, 2026-10-01. GO; no remaining actionable findings.

Reviewed revision: source/test manifest SHA256 ae4ba49c16bf40c86bfe645bb853914b86330ba9c63812197704a5b043a3f508, recorded in build/codex-retained-wake-product-reviewed-files.json.

Verification adequacy: final 74-case focused run, affected lane plus ordered isolation replay, preserved hook evidence, and native secure-scratch run plus exact transport rerun support local implementation acceptance. No new installed automatic lifecycle qualification is claimed. Accepted best-effort check/send race remains. Optional wake stays disabled unless explicitly enabled on both sides.

Next: opt-in deployment and a normal-mode installed smoke witness are separate from this completed local implementation. No live authority, pending experimental action, or automatic configuration change was introduced. Current branch remains feat/codex-retained-wake-product; source/test changes remain local and uncommitted under the quick-iteration instruction. Canonical roadmap: roadmap/features/add-wake-first-relay-delivery.md.
