# Codex MCP startup isolation

<!-- agent-workflow:start -->
**Outcome:** Codex chats remain resumable when Pallium MCP cannot initialize, while healthy cold startup retains the complete Pallium tool catalog.

**Target:** Pallium Codex MCP setup and startup integration.

**Scope:** app/cli/setup_codex.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_codex_mcp_stdio.py; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; this Work Record.

**Constraints:** Preserve identity and scope validation, credentials, explicit user settings, per-tool approvals, complete healthy tool exposure, existing timeouts and delivery/receipt/ACK/no-replay contracts. No global timing changes, new dependencies or lifecycle framework. Keep work isolated; no live configuration, installation, upgrade, worktree restoration, service or host restart, or denied-operation retry. Keep this fix independent of unrelated refactoring and preserve ongoing work.

**Completion criteria:** A deleted chat directory does not break MCP launch; unavailable Pallium startup does not make default chat resume fatal and tool unavailability is visible; healthy cold startup retains all callable tools; generated configuration is idempotent and preserves explicit choices; caller-surface E2E, applicable whole-change validation and independent source/result reviews pass. Source evidence is not installed-host acceptance.

**Requirement baseline:**
{"source":"Initial Work Record, public representation; complete original retained privately.","outcome":"Codex chats remain resumable when Pallium MCP cannot initialize, while healthy cold startup retains the complete Pallium tool catalog.","scope":"app/cli/setup_codex.py; tests/test_codex_integration.py; a narrowly scoped startup E2E test if existing caller-surface coverage cannot express the regression; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; this Work Record.","constraints":"Preserve identity and scope validation, credentials, explicit user settings, per-tool approvals, complete healthy tool exposure, existing timeouts and delivery/receipt/ACK/no-replay contracts. No global timing changes, new dependencies or lifecycle framework. Keep work isolated; no live configuration, installation, upgrade, worktree restoration, service or host restart, or denied-operation retry. Keep this fix independent of unrelated refactoring and preserve ongoing work.","completion_criteria":"A deleted chat directory does not break MCP launch; unavailable Pallium startup does not make default chat resume fatal and tool unavailability is visible; healthy cold startup retains all callable tools; generated configuration is idempotent and preserves explicit choices; caller-surface E2E, applicable whole-change validation and independent source/result reviews pass. Source evidence is not installed-host acceptance."}

**Behavior changes:**
[{"target":"task-context.scope","classification":"coverage-only","before":"app/cli/setup_codex.py; tests/test_codex_integration.py; a narrowly scoped startup E2E test if existing caller-surface coverage cannot express the regression; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; this Work Record.","after":"app/cli/setup_codex.py; tests/test_codex_integration.py; tests/test_codex_wake.py; tests/test_codex_mcp_stdio.py; docs/codex-integration.md; roadmap/features/fix-codex-mcp-startup-isolation.md; roadmap/board.md; roadmap/scope.md; this Work Record.","reason":"The retained independent reviewer and task owner selected the existing real stdio caller surface and dedicated-profile regressions instead of an unnamed new E2E file. All other scoped paths and product obligations remain; no protected contract change."}]

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:fix-codex-mcp-startup-isolation"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The installer is a watched runtime/process surface. Stable launch-directory and explicit-setting preservation affect startup availability; identity, security, persistence and existing timeout contracts remain unchanged.

**Discovery:** Generated stdio startup can inherit a removed chat directory. Existing setup also reconstructs server tables and must preserve supported explicit choices and the intentional Relay profile subset. Non-BMP Unicode and DEL need TOML-safe rendering. These source corrections do not establish a nonfatal slow-start policy or host-visible catalog acceptance.

**Material assumptions:** The native cwd setting can isolate a generated launch from a removed directory while preserving explicit cwd, supported transport and runtime identity. New-server required and timeout defaults remain unchanged. Healthy catalog acceptance means eventual complete same-chat host-visible callable tools with truthful status, not a first optional-grace snapshot; configuration and stdio evidence do not prove that host behavior.

**Plan:** Deliver only the reviewed stable-directory partial slice. Set generated stdio cwd to the resolved configuration parent when absent; preserve supported explicit startup settings, launch/package provenance, credentials, identity and per-tool approvals. Prevalidate base and profile candidates before the first write, without claiming arbitrary IO transaction atomicity. Keep the intentional profile tool subset. Preserve non-BMP Unicode and escape DEL in both existing TOML render paths. Verify deleted/conflicting directories, configured-package provenance, real stdio catalog/identity, invalid candidates, explicit settings and repeat setup/removal through existing caller surfaces. Full nonfatal startup, eventual host-visible catalog and installed qualification remain open; no default-policy migration or installed action is included.

**Verification plan:**
- Generated launch -> existing integration caller test for configured-package provenance, deleted/conflicting chat directories, Unicode/spaces and generated stable cwd.
- Real stdio -> existing initialize/list/call identity witness compares the complete base catalog schemas with the reference server; retain per-tool identity/receipt/error controls. This is not the native host readiness discriminator.
- Settings and lifecycle -> existing setup/profile callers cover explicit true/false/cwd/readiness/timeouts, credentials, approvals, intentional tool subset, nested/malformed candidates, no write before validation, repeat install and remove.
- Whole source -> existing trusted selector and normal full non-slow CI can cover the affected files once; preserve actual first failures, witness execution/skips and platform limits. Windows smoke covers integration setup, while stdio/profile Windows qualification remains separate.
- Full product requirement -> separately selected native-host qualification must distinguish executable/server-start failure from service/tool-call failure and demonstrate usable resume with truthful unavailability, plus eventual complete callable catalogs on slow empty-cache and warm-cache healthy startup. No cache/global-timing shortcut or first-snapshot proxy qualifies this.
- Final result -> independent source/record/composition and runtime/result review, with explicit native/platform/installed limits. No application/native execution or live rollout is selected by this private preparation.

**Plan review:** Agent technical review: Independent review accepted the stable-directory partial source and its Unicode correction at their exact revisions. The earlier Unicode source finding remains retained evidence and is closed at source level only. Unchanged source review is reused. Final first-public-record/privacy/governance/composition review and current-candidate runtime/result verification remain pending.

**Approvals:** User requested that this bug be added to the managed fixes. Human plan approval is not required at the current risk level. This authorizes isolated repository work, not installed-environment changes.

**State:** Blocked
<!-- agent-workflow:end -->

## Verification status

The stable-directory and Unicode corrections passed independent source review. Authored application and native tests remain unexecuted. Static source checks are separate from final composition/governance review and runtime qualification.

This is a partial contribution. Nonfatal default resume, eventual complete host-visible callable catalogs, full platform/native behavior and installed recovery remain unverified. No feature completion or installed change is claimed.
