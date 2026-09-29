# Sanitized Codex inventory failure stages

Owner: relay-dev. Canonical feature: `roadmap/features/add-wake-first-relay-delivery.md`; manager owns roadmap, merge, installed rollout and any later live qualification. PR #256 and its completed Work Record remain unchanged.

<!-- agent-workflow:start -->
**Outcome:** Identify the failing service-side inventory stage without exposing native connection data or changing execution behavior.

**Target:** Optional Windows Codex inventory custody in the existing Pallium service.

**Scope:** app/codex_bridge_pipe.py, tests/test_codex_bridge_pipe.py, docs/designs/codex-mcp-desktop-bridge.md and this Work Record.

**Constraints:** Diagnostics only. No new native action, retry, admission, reconnect, authority, cleanup or fence behavior; no public MCP or protected proof schema changes. Never log exception text/tracebacks, endpoint, environment, native response or inventory contents. No live trial/setup/rearm, archive/unload, process kill or Desktop restart. Preserve scope, model/effort, user trust and existing assertions. Preserve completed PR #256 history and the separate wake-registry incident.

**Completion criteria:** Injected caller-path failures distinguish native open, peer check, authority/source recheck, inventory write/read/validation and proof publication through fixed sanitized service diagnostics. The original failing stage/category survives later cleanup failures and lossy public normalization. Unknown diagnostic input and failed log sinks cannot expose data or alter failure/cleanup behavior. Success adds no failure event; repeated denied calls add no native submissions. Public caller results and exact protected proof fields remain unchanged. Focused native caller E2E, affected subsystem, whole-change selected checks, one full non-slow run and independent review qualify the immutable change; fresh PR CI precedes manager merge/install. Diagnostics alone do not qualify transport lifetime or unloaded wake.

**Requirement baseline:**
{"source":"manager diagnostic implementation assignment, 2026-09-29, thread 01a0d7ce-83c6-77e2-90f7-d413894059e1","outcome":"Identify the failing service-side inventory stage without exposing native connection data or changing execution behavior.","scope":"app/codex_bridge_pipe.py, tests/test_codex_bridge_pipe.py, docs/designs/codex-mcp-desktop-bridge.md and this Work Record.","constraints":"Diagnostics only. No new native action, retry, admission, reconnect, authority, cleanup or fence behavior; no public MCP or protected proof schema changes. Never log exception text/tracebacks, endpoint, environment, native response or inventory contents. No live trial/setup/rearm, archive/unload, process kill or Desktop restart. Preserve scope, model/effort, user trust and existing assertions. Preserve completed PR #256 history and the separate wake-registry incident.","completion_criteria":"Injected caller-path failures distinguish native open, peer check, authority/source recheck, inventory write/read/validation and proof publication through fixed sanitized service diagnostics. The original failing stage/category survives later cleanup failures and lossy public normalization. Unknown diagnostic input and failed log sinks cannot expose data or alter failure/cleanup behavior. Success adds no failure event; repeated denied calls add no native submissions. Public caller results and exact protected proof fields remain unchanged. Focused native caller E2E, affected subsystem, whole-change selected checks, one full non-slow run and independent review qualify the immutable change; fresh PR CI precedes manager merge/install. Diagnostics alone do not qualify transport lifetime or unloaded wake."}

**Risk:** High

**Complexity:** Moderate

**Reason:** Native capability custody is a security boundary. Observational logging must neither leak private data nor perturb failure fences, cleanup or proof semantics. No public API change is intended.

**Discovery:** The service normalizes native errors, transport errors, invalid responses and proof-write failures to native-failed. Public error booleans are defaults, not intermediate connection history. A fresh failure phase establishes final preconnection authorization, not successful open. Existing private-caller/native fixtures already cover missing pipe, peer lookup failure, one-slot fences and strict proof fields. No new harness is needed. The actual saved failure-phase observation booleans were false; it cannot be localized retrospectively. The design's proposed/implementation-in-progress wording lags merged PR #256; update only relevant inventory status and diagnostic limits.

**Material assumptions:** A fixed stage and allowlisted pre-normalization category are sufficient for the next diagnosis decision; if not, report the exact missing distinction rather than expose native data. Log handlers may fail; diagnostics must remain observational. Cleanup may fail after the original exception; retain its first diagnostic instead of replacing it. No native/runtime proof is inferred from test fixtures. Parallel wake-registry work is separate; flag a shared-path overlap before edits.

**Plan:** First invoke Agent Workflow, evaluate whole-change applicability and classify risk before code edits. Reuse the clean completed managed checkout on feat/codex-inventory-failure-stages from main 01b3f065; seed and commit this separate record, then obtain clean-context non-implementer plan review. Reuse stdlib logging and the current service flow. Track a bounded fixed stage in RAM immediately before existing actions, with at most one original failure diagnostic per registration/observation attempt. Report only a fixed stage/category and existing non-secret epoch/revision correlation; no exception representation. Capture before cleanup and public category normalization; subsequent cleanup/proof failures must not overwrite it. Keep logging failures contained without changing existing error/cleanup handling. Cover both initial observation and the existing post-exit observation, not startup/bootstrap or Relay wake. Add injected-failure caller E2E using the existing isolated fake Desktop and real private service/client, including proof publication and failing cleanup/log sinks, success/idempotence and sanitization. Run focused development tests, complete native/affected MCP coverage and whole-change selector; run the reported full non-slow/check lanes once. Obtain immutable result/security/API-boundary review, publish a separate PR and qualify fresh CI. Manager owns merge/install and any later exact live attempt.

**Verification plan:** Each existing caller failure boundary -> bounded stage/category log, unchanged public response/proof fields and original cleanup/fence/native call-count assertions in tests/test_codex_bridge_pipe.py. Cleanup or log-sink failure -> original stage retained and existing exception/resource handling unchanged. Unknown/Unicode/private sentinel input -> allowlist fallback with no endpoint/message/response text. Success and repeated registration -> no failure log and unchanged connection/inventory counts. Later post-exit failure -> original after-observation stage with no false historical PASS. Coherent change -> whole-change selector, full non-slow suite once, fresh import/Redline/workflow checks and independent immutable result review; standalone untraced native suite supplies coverage excluded by ordinary PR CI.

**Plan review:** Pending clean-context independent technical review; no application/test edits until accepted.

**Approvals:** Approved by user 2026-09-28: "This is a night job so i give blanket approval" (source 15322050-ec54-43b1-bef2-44b942ea0d60). The manager expressly assigns this bounded diagnostics-only implementation on 2026-09-29 under that standing approval and delegated technical review. This is not permission to bypass a fresh rejection or perform live actions.

**Exceptions:** None

**State:** Blocked
<!-- agent-workflow:end -->

## Planning

Existing applicability configuration denies a documentation-only exemption because the intended scope includes application/native code and tests. High/Moderate is retained conservatively; no boundary or public/proof contract change is proposed. Source mapping and current live evidence are reused; raw private incident data is not copied here. Completed PR #256 is merged, its attached checkout is clean, and no process other than the inspection shell uses it. This new branch preserves that old branch and record.

## Evidence

No application edit, test run or live action yet. The separate wake-registry owner is manager-delegated; intended shared-path set is reported before implementation.
