<!-- agent-workflow:start -->
**Outcome:** Relay agents can detect the resolved destination of every send and are explicitly guided not to reuse unverified exact endpoint IDs across workspaces.

**Target:** Pallium Relay MCP integration.

**Scope:** `app/mcp/server.py`, Relay MCP/E2E tests, `docs/agent-relay.md`, and the three repository-owned Pallium integration skill copies.

**Constraints:** Preserve intentional cross-container Relay routing, selector compatibility, response budgets, redaction, and existing HTTP contracts; do not add dependencies or change persistence.

**Completion criteria:** A long Relay send response exposes the resolved endpoint, runtime, session, container, state, and health within budget; guidance requires current discovery/alias use for role recipients; short and error responses remain compatible; all affected and full tests pass.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `app/mcp/server.py` is a gray/watch runtime surface under agent-redline; tests/docs are blue. One shared formatter and mirrored guidance make this a coherent single-session change.

**Discovery:** Incident `relay-msg-99a547d886e2482bbc8a7da265cbfb7c` used a historically remembered canonical endpoint and was correctly routed cross-container to `git:github.com/rore/dictation-app`. The HTTP/store response already contained resolved delivery identity, but `_relay_text` discarded it when compacting a long payload, leaving only counts/states. Current guidance calls endpoint IDs canonical without requiring revalidation. Cross-container exact routing is intentional and covered by `tests/test_cross_container_relay_e2e.py`.

**Material assumptions:** Compact resolved-delivery metadata plus safer selector guidance is the smallest sufficient contract. If the architect requires pre-admission expected-container enforcement, return to planning and reclassify for API/schema scope before editing.

**Plan:** Preserve compact response budgeting while adding a bounded per-delivery projection containing resolved recipient identity and state. Add a caller-surface MCP test for a long cross-container send, unit coverage for the compact formatter, and consistent guidance across Codex/Claude/OpenCode skills plus Relay docs. Do not alter routing semantics. Stop and replan if architect review requires an HTTP request/schema guard.

**Verification plan:** Long cross-container MCP send shall expose its resolved destination within the response budget → focused MCP E2E test. Compact formatter shall retain destination identity without secrets and remain bounded → formatter unit test. Existing short/error/send/receive behavior shall remain compatible → affected MCP and cross-container test files. Final regression → `python -m pytest tests/ -x -q`, workflow checker, redline checker, PR CI and independent result review.

**Plan review:** Pending clean-context review by Pallium architect `@pall-arc`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Established the incident from persisted Relay metadata and traced exact-selector resolution through storage, HTTP, MCP client, and MCP response compaction. No product code edited; awaiting architect validation.

## Evidence

- Persisted delivery metadata resolves the mistaken endpoint to `git:github.com/rore/dictation-app`; current `@pall-arc` resolves to `git:github.com/rore/pallium`.
- `_relay_text` in `app/mcp/server.py` removes all resolved delivery identity when a long send exceeds the MCP response budget.

## Plan review

Pending architect response to Relay message `relay-msg-06b03e064992409a8d5a765fab34b511`.

## Result review

Pending.
