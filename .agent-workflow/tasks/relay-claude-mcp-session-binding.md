<!-- agent-workflow:start -->
**Outcome:** Claude Code setup launches Pallium MCP as a session-bound stdio child process, so Relay receive/ACK tools resolve the active Claude session instead of failing behind the shared service HTTP transport.

**Target:** app/cli/setup_claude_code.py, tests/test_claude_code_integration.py, docs/claude-code-integration.md

**Scope:** Replace Claude's user-scoped HTTP MCP registration with the existing stdio `python -m app.run mcp` pattern, injecting only the static runtime/base URL/Python path environment required by the child; add an installer regression and align docs.

**Constraints:** Keep the Pallium service as the data-plane HTTP target; do not add a new identity mechanism, dependency, protocol, or service restart path. Session identity must continue to come from Claude's runtime process boundary, not model input.

**Completion criteria:** A setup invocation registers `pallium` with Claude as stdio using the active Python and `PALLIUM_AGENT_REF=claude-code`; the regression fails for HTTP registration; focused and full relevant tests pass; the installed local Claude MCP reports stdio after reinstall.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/cli/setup_claude_code.py` is a runtime/process watch-zone path. The change is one installer command plus a regression and docs, but it controls the trusted Relay session-identity boundary.

**Discovery:** PR #76 correctly made MCP Relay receive derive Claude identity from its parent process, but the post-merge installer still registered the shared service HTTP MCP. That server cannot observe the invoking Claude process. Codex already uses the required stdio child-process pattern; Claude CLI supports stdio registration after `--` with command, args, and `-e` environment entries.

**Material assumptions:**
- Claude CLI user-scope MCP registration supports stdio command/args plus repeated `-e KEY=VALUE`; disproved by focused mocked-command regression or real `claude mcp get pallium`; action: stop and inspect current CLI help rather than inventing config.
- The active Pallium Python can run `-m app.run mcp` when given the repo on PYTHONPATH; disproved by local MCP startup failure; action: reuse the already verified Codex environment construction.

**Plan:** Reuse the existing Codex stdio environment construction semantics in the Claude installer with the smallest local helper(s); assert the exact Claude CLI registration shape and absence of HTTP transport; update the integration doc; run focused tests and a real local reinstall; create one PR, resolve findings once, merge after required checks.

**Verification plan:**
- When setup registers MCP, Claude shall receive a stdio command with `PALLIUM_AGENT_REF=claude-code` and no HTTP transport flag → mocked subprocess regression.
- When the focused Claude integration suite runs, existing hook/skill behavior shall remain unchanged → `pytest tests/test_claude_code_integration.py -q`.
- When local setup is rerun, `claude mcp get pallium` shall report stdio → real installation smoke check.
- When the final diff is proposed, workflow and relevant test gates shall pass → agent-workflow checker and PR CI.

**Plan review:** Self-review under the user-directed closure exception below; the change reuses the already reviewed Codex stdio pattern and adds a real-install verification.

**Approvals:** Not required at this risk level.

**Exceptions:**
- rule: approval.elevated_clean_context_review_present
  reason: The user explicitly directed this agent to close remaining issues itself and avoid another review cycle.
  scope: Plan review for this narrow post-merge installer correction only.
  approver: user
  expiry: 2026-08-28
  compensating_validation: Exact subprocess regression, focused suite, real Claude reinstall inspection, PR CI, and review-thread resolution before merge.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Branch: fix/relay-claude-mcp-session-binding

Implemented the session-bound stdio registration by replacing Claude setup's shared HTTP registration. Added the exact subprocess regression and aligned public setup documentation. `apply_patch` failed with the documented Windows CreateProcessWithLogonW 1327 error; the three planned files were changed with narrow deterministic replacements.

## Evidence

- Focused Claude integration suite: 12 passed.
- Claude + Relay MCP caller-surface suites: 41 passed.
- Real local transition: `claude mcp get pallium` changed from connected HTTP to connected stdio, with the active Python command and required runtime/base URL/PYTHONPATH environment.
- Service signals: `/health` reports `ok`; `/status` reports `embedding_provider_ok=true`; queue health has no pending work, no unclaimable work, and no active leases (recorded failures are historical 2026-08-25 authorization failures).
- `git diff --check`: clean.

## Result review

Self-review: the final diff is limited to installer transport selection, one caller-shape regression, and one documentation correction. No Relay protocol or identity resolution code changed.
