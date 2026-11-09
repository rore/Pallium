# Codex MCP startup isolation

<!-- agent-workflow:start -->
**Outcome:** Codex chats remain resumable when Pallium MCP cannot initialize, while healthy cold startup retains the complete Pallium tool catalog.

**Target:** Pallium Codex MCP setup and startup integration.

**Scope:** app/cli/setup_codex.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_codex_mcp_stdio.py; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; tests/test_agent_relay_e2e.py; this Work Record.

**Constraints:** Preserve identity and scope validation, credentials, explicit user settings, per-tool approvals, complete healthy tool exposure, existing timeouts and delivery/receipt/ACK/no-replay contracts. No global timing changes, new dependencies or lifecycle framework. Keep work isolated; no live configuration, installation, upgrade, worktree restoration, service or host restart, or denied-operation retry. Keep this fix independent of unrelated refactoring and preserve ongoing work.

**Completion criteria:** A deleted chat directory does not break MCP launch; unavailable Pallium startup does not make default chat resume fatal and tool unavailability is visible; healthy cold startup retains all callable tools; generated configuration is idempotent and preserves explicit choices; caller-surface E2E, applicable whole-change validation and independent source/result reviews pass. Source evidence is not installed-host acceptance.

**Requirement baseline:**
{"source":"Initial Work Record, public representation; complete original retained privately.","outcome":"Codex chats remain resumable when Pallium MCP cannot initialize, while healthy cold startup retains the complete Pallium tool catalog.","scope":"app/cli/setup_codex.py; tests/test_codex_integration.py; a narrowly scoped startup E2E test if existing caller-surface coverage cannot express the regression; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; this Work Record.","constraints":"Preserve identity and scope validation, credentials, explicit user settings, per-tool approvals, complete healthy tool exposure, existing timeouts and delivery/receipt/ACK/no-replay contracts. No global timing changes, new dependencies or lifecycle framework. Keep work isolated; no live configuration, installation, upgrade, worktree restoration, service or host restart, or denied-operation retry. Keep this fix independent of unrelated refactoring and preserve ongoing work.","completion_criteria":"A deleted chat directory does not break MCP launch; unavailable Pallium startup does not make default chat resume fatal and tool unavailability is visible; healthy cold startup retains all callable tools; generated configuration is idempotent and preserves explicit choices; caller-surface E2E, applicable whole-change validation and independent source/result reviews pass. Source evidence is not installed-host acceptance."}

**Behavior changes:**
[{"target":"task-context.scope","classification":"coverage-only","before":"app/cli/setup_codex.py; tests/test_codex_integration.py; a narrowly scoped startup E2E test if existing caller-surface coverage cannot express the regression; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; this Work Record.","after":"app/cli/setup_codex.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_codex_mcp_stdio.py; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; this Work Record.","reason":"The retained independent reviewer and task owner selected the existing real stdio caller surface and dedicated-profile regressions instead of an unnamed new E2E file. All other scoped paths and product obligations remain; no protected contract change."},{"target":"task-context.scope","classification":"coverage-only","before":"app/cli/setup_codex.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_codex_mcp_stdio.py; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; this Work Record.","after":"app/cli/setup_codex.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_codex_mcp_stdio.py; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; tests/test_agent_relay_e2e.py; this Work Record.","reason":"Include the existing HTTP derived-reply attribution/idempotence witness for a bounded two-enrollment prerequisite setup correction. The audited semantic fixture ends before send, claim, ACK or reply; caller requirements and native subject failures remain unchanged."}]

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:fix-codex-mcp-startup-isolation"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The installer is a watched runtime/process surface. Stable launch-directory and explicit-setting preservation affect startup availability; identity, security, persistence and existing timeout contracts remain unchanged.

**Discovery:** Generated stdio startup can inherit a removed chat directory. Existing setup also reconstructs server tables and must preserve supported explicit choices and the intentional Relay profile subset. Non-BMP Unicode and DEL need TOML-safe rendering. These source corrections do not establish a nonfatal slow-start policy or host-visible catalog acceptance. The first normal Linux 3.13 run failed on initial participant enrollment before the existing derived-reply subject. The saved 503 and acquisition observations do not establish a physical cause or a production startup/acquisition repair.

**Material assumptions:** The native cwd setting can isolate a generated launch from a removed directory while preserving explicit cwd, supported transport and runtime identity. New-server required and timeout defaults remain unchanged. Healthy catalog acceptance means eventual complete same-chat host-visible callable tools with truthful status, not a first optional-grace snapshot; configuration and stdio evidence do not prove that host behavior.

**Plan:** Deliver only the reviewed stable-directory partial slice. Set generated stdio cwd to the resolved configuration parent when absent; preserve supported explicit startup settings, launch/package provenance, credentials, identity and per-tool approvals. Prevalidate base and profile candidates before the first write, without claiming arbitrary IO transaction atomicity. Keep the intentional profile tool subset. Preserve non-BMP Unicode and escape DEL in both existing TOML render paths. Verify deleted/conflicting directories, configured-package provenance, real stdio catalog/identity, invalid candidates, explicit settings and repeat setup/removal through existing caller surfaces. Full nonfatal startup, eventual host-visible catalog and installed qualification remain open; no default-policy migration or installed action is included. Correct only test_delivery_derived_reply_is_attributed_scoped_and_idempotent in tests/test_agent_relay_e2e.py: parameterize the existing relay_admission_clock fixture as semantic, scope exactly its two original initial enrollment calls with expected_admissions=2, capture original observer-decorated transaction entry and sqlite_queue.time, and assert exact immediate restoration before the first send. Preserve both helper-enforced HTTP 200 checks and every later native request/assertion/cleanup. No global helper, fixture default, production clock, timeout, retry, native variant or broader stabilization change.

**Verification plan:**
- Generated launch -> existing integration caller test for configured-package provenance, deleted/conflicting chat directories, Unicode/spaces and generated stable cwd.
- Real stdio -> existing initialize/list/call identity witness compares the complete base catalog schemas with the reference server; retain per-tool identity/receipt/error controls. This is not the native host readiness discriminator.
- Settings and lifecycle -> existing setup/profile callers cover explicit true/false/cwd/readiness/timeouts, credentials, approvals, intentional tool subset, nested/malformed candidates, no write before validation, repeat install and remove.
- Whole source -> existing trusted selector and normal full non-slow CI can cover the affected files once; preserve actual first failures, witness execution/skips and platform limits. Windows smoke covers integration setup, while stdio/profile Windows qualification remains separate.
- Full product requirement -> separately selected native-host qualification must distinguish executable/server-start failure from service/tool-call failure and demonstrate usable resume with truthful unavailability, plus eventual complete callable catalogs on slow empty-cache and warm-cache healthy startup. No cache/global-timing shortcut or first-snapshot proxy qualifies this.
- Final result -> independent source/record/composition and runtime/result review, with explicit native/platform/installed limits. No application/native execution or live rollout is selected by this private preparation.
- Derived-reply prerequisite correction -> statically verify exactly the two original enrollment calls inside the existing audited scope, immediate original-method/time restoration before the subject, and every original reply/ACK/identity/Unicode/conflict/missing/cross-container assertion unchanged. Preserve the first failed normal profile. Newly authored source remains unexecuted; exact changed-source review precedes a separately selected new-head full CI run.

**Plan review:** Agent technical review: Independent review accepted the stable-directory partial source and its Unicode correction at their exact revisions. The earlier Unicode source finding remains retained evidence and is closed at source level only. Unchanged source review is reused. Final first-public-record/privacy/governance/composition review and current-candidate runtime/result verification remain pending. Independent first-failure result review selected this exact bounded prerequisite mechanism and restoration boundary; it did not accept unauthored source or explain the physical cause. Changed-source/privacy/record review remains pending under the same task.

**Approvals:** User requested that this bug be added to the managed fixes. Human plan approval is not required at the current risk level. This authorizes isolated repository work, not installed-environment changes.

**State:** Blocked
<!-- agent-workflow:end -->

## Verification status

The stable-directory and Unicode corrections passed independent source review. Authored application and native tests remain unexecuted. Static source checks are separate from final composition/governance review and runtime qualification.

This is a partial contribution. Nonfatal default resume, eventual complete host-visible callable catalogs, full platform/native behavior and installed recovery remain unverified. No feature completion or installed change is claimed.

## Derived-reply prerequisite correction plan

Resume the same owning task from the exact published head after its normal run completed. Only this Work Record and tests/test_agent_relay_e2e.py are selected for the new source delta. The whole application contribution remains non-exempt, Elevated risk and Moderate complexity; the ordinary test is blue and the unchanged installer remains gray/watch. The existing public baseline, private complete baseline, original approvals and full nonfatal/catalog/runtime/installed requirements remain unchanged.

The [first normal run](https://github.com/rore/Pallium/actions/runs/42621298939) remains failed on Linux 3.13. Linux 3.12, Windows smoke and governance passed at that exact prior head; they are not results for this new correction. The original registration failure and its raw evidence are retained. Both enrollments are prerequisites for the reply contract. Use the existing audited fixture with exact count two and per-thread native fallback, leaving all subject operations native. No application tests, imports, compile, CI, native-host or installed action is selected during source preparation.

## Derived-reply source preparation result

Only the selected test and this Work Record changed. The semantic fixture scope contains exactly the two original enrollment calls, including their helper-enforced HTTP 200 checks. Two immediate restoration assertions precede the unchanged first send. Static AST comparison preserves all 20 original assertion predicates and every subject statement from the first send onward; every other module-level definition is identical. No global helper, shared fixture, production clock, deadline, retry, native variant or caller expectation changed.

The correction is authored and unexecuted. Source/privacy/record review remains pending before any separately selected new-head validation or publication. The failed prior profile remains evidence; no physical-cause, production acquisition repair, full nonfatal/catalog qualification, feature completion or installed recovery is claimed.
