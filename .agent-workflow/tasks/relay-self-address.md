# Relay self address

<!-- agent-workflow:start -->
**Outcome:**
An agent can answer “what is your Relay address?” through one trusted MCP call that returns its canonical endpoint and optional alias.

**Target:**
Pallium.

**Scope:**
Add one self-bound Relay MCP tool by reusing current session identity and the existing session-list client; add focused MCP tests and integration documentation.

**Constraints:**
No new HTTP API, identity source, dependency, Relay state mutation, or caller-supplied runtime/session identity. Existing Relay behavior and selector formats remain unchanged.

**Completion criteria:**
When a configured Relay session calls `pallium_relay_address`, it returns that exact session’s `relay-session-...` selector and optional `@name`; missing or ambiguous trusted identity fails closed without guessing.

**Requirement baseline:**
{"source":"user request, 2026-09-22","outcome":"An agent can answer “what is your Relay address?” through one trusted MCP call that returns its canonical endpoint and optional alias.","scope":"Add one self-bound Relay MCP tool by reusing current session identity and the existing session-list client; add focused MCP tests and integration documentation.","constraints":"No new HTTP API, identity source, dependency, Relay state mutation, or caller-supplied runtime/session identity. Existing Relay behavior and selector formats remain unchanged.","completion_criteria":"When a configured Relay session calls `pallium_relay_address`, it returns that exact session’s `relay-session-...` selector and optional `@name`; missing or ambiguous trusted identity fails closed without guessing."}

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
Agent-redline classifies `app/mcp/server.py` as a gray runtime surface. The change is one MCP tool over an existing client method, with no red-zone or boundary touch.

**Discovery:**
No dedicated self-address tool exists. `current_relay_identity` already resolves trusted per-call identity, and `relay_recipients` already returns the current endpoint and alias through `GET /relay/sessions`.

**Material assumptions:**
The exact runtime/session filter returns zero or one endpoint; multiple matches disprove this and must fail closed. Current-turn registration normally makes the endpoint visible; a zero result remains an actionable error rather than guessed identity. The existing `core.relay.parse_selector` is the canonical validator for endpoint and alias selectors.

**Plan:**
Add `pallium_relay_address` beside the recipient tool. Resolve identity with `current_relay_identity`, query `relay_recipients` with the exact pair and `include_inactive=true`, then require one mapping whose runtime/session exactly match the trusted identity and whose endpoint/optional alias pass `core.relay.parse_selector`. Return only `runtime`, `session_ref`, `exact_selector`, and optional `alias_selector`. Add focused registration; Claude environment and Codex per-call metadata identity; malformed, zero, and ambiguous response; and registered/named/inactive caller-surface lifecycle tests. Update the Relay guide and Claude/Codex tool-list usage text. Stop if implementation requires a new HTTP route, schema, or identity source.

**Verification plan:**
When a registered, unnamed/named, or inactive session asks for its address, the MCP tool shall return only its trusted identity and valid exact/optional alias selectors → focused real MCP/ASGI lifecycle test. When Claude integration identity or Codex per-call metadata is missing/conflicting, the tool shall fail closed before HTTP → focused MCP tests. When the session response is missing, malformed, mismatched, or ambiguous, the tool shall fail closed without guessing → focused mocked MCP tests. Existing Relay MCP surfaces shall remain intact → affected test files and repository-required checks.

**Plan review:**
Approved by clean-context agent `/root/review_relay_address_plan`; exact validation/output and identity/lifecycle coverage clarified.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

Clean-context review initially requested exact selector validation, a fixed output contract, Codex request-metadata coverage, and inactive/malformed lifecycle cases. The plan was updated; reviewer approved it with no remaining blocker.

## Implementation

Added pallium_relay_address over trusted current-session identity and the existing exact recipient lookup. The tool validates the unique returned endpoint and optional alias with canonical Relay parsing, returns only the two selectors plus runtime/session identity, and includes inactive endpoints. Updated caller docs and MCP tests. apply_patch later failed with the known Windows CreateProcessWithLogonW 1327 launcher error, so subsequent edits used narrowly scoped deterministic replacements in the named files.

## Evidence

Focused self-address and real Codex stdio tests: 11 passed; final response-validation regression: 7 passed. Complete affected files: 180 passed. Required last-failed check: 5361 deselected, no failures selected. Full repository suite: 5110 passed, 34 skipped, 2 xfailed in 223.23s; the later test-only session-mismatch case passed in the focused and affected reruns.

## Result review

Independent implementation review found no correctness, budget, API-compatibility, or broad-replacement defects. It requested Work Record completion and an explicit session-mismatch test; both are addressed. The existing runtime-mismatch case was retained.
