# MCP Relay sender retry identity

Canonical source: `roadmap/features/add-wake-first-relay-delivery.md`, sender retry identity checklist, at `a2726453323a363b0656ddf3d87a2d4b0d86937e`. Roadmap edits remain with the parent task's designated shared checkout.

<!-- agent-workflow:start -->
**Outcome:** MCP send callers can retry a committed send after response loss using one caller-supplied message identity without duplicating the durable message.

**Target:** Pallium Relay MCP send.

**Scope:** app/mcp/server.py, tests/test_relay_mcp_tools.py, docs/agent-relay.md, and this Work Record.

**Constraints:** Preserve omitted-ID behavior and existing sender/payload/recipient/expiry conflict checks. No storage, schema, scheduler, native wake, installed environment, or response redesign changes. Preserve all protected behavior contracts.

**Completion criteria:** Same-ID retry after committed-send response loss yields one message and delivery through public reads; conflicting sender, payload, recipient or expiry rejects without mutation; omitted IDs still generate independent messages; empty and over-128 IDs reject, 1/128-character Unicode IDs succeed, and omitted/null expiry semantics remain intact.

**Requirement baseline:**
{"source":"roadmap/features/add-wake-first-relay-delivery.md@a2726453323a363b0656ddf3d87a2d4b0d86937e","outcome":"MCP send callers can retry a committed send after response loss using one caller-supplied message identity without duplicating the durable message.","scope":"app/mcp/server.py, tests/test_relay_mcp_tools.py, docs/agent-relay.md, and this Work Record.","constraints":"Preserve omitted-ID behavior and existing sender/payload/recipient/expiry conflict checks. No storage, schema, scheduler, native wake, installed environment, or response redesign changes. Preserve all protected behavior contracts.","completion_criteria":"Same-ID retry after committed-send response loss yields one message and delivery through public reads; conflicting sender, payload, recipient or expiry rejects without mutation; omitted IDs still generate independent messages; empty and over-128 IDs reject, 1/128-character Unicode IDs succeed, and omitted/null expiry semantics remain intact."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:** High

**Complexity:** Simple

**Reason:** app/mcp/server.py is a red API contract surface requiring api-review. One optional argument exposes an existing client/storage contract; no new storage behavior or dependency.

**Discovery:** MCP tool omits message_id although its docstring already describes existing-ID expiry. PalliumMcpClient.relay_send already accepts optional message_id, generates a UUID when absent, and passes explicit identities unchanged. RelaySendRequest accepts 1–128 characters. SQLite relay_send matches sender identity, payload, recipient selector, redaction, parent, and supplied expiry before returning the existing status. tests/test_relay_mcp_tools.py already provides registered FastMCP call_tool plus real HTTP ASGI/storage fixtures and public status/turn reads. Existing callers omit the new argument and need no edits. No behavior_contracts path changes.

**Material assumptions:** Existing client/storage identity semantics fully implement the required contract. If caller-surface regression exposes a defect beyond tool forwarding, return to planning rather than extending persistence scope. No installed or native qualification is needed to prove this repository contract.

**Plan:** Add optional nullable message_id with Field(min_length=1, max_length=128) to registered pallium_relay_send and forward it unchanged to relay_send. Briefly document generating/reusing one ID for identical retries after uncertain response; omitted ID remains a new send. Extend existing FastMCP/ASGI tests: commit via real HTTP then suppress its response, retry same ID, inspect public status and claim/ACK lifecycle; parameterize conflicts and identity boundaries, and assert omitted IDs remain independent. Reuse existing expiry fixtures and error helpers. Stop on scope expansion, conflicting baseline, or unmet review/approval gate. No production code edits until technical plan review and exact-scope human approval are recorded.

**Verification plan:** Registered schema asserts optional nullable 1–128-character string. Caller-surface fault test drives FastMCP call_tool → client → HTTP → SQLite, loses the committed response, retries, observes one message/delivery via status and turn, ACKs, and observes no second delivery. Sender/payload/recipient/expiry conflicts assert HTTP 409 and unchanged original status/inboxes. Boundary cases include empty/129 rejection and 1/128 Unicode acceptance. Omitted/null ID calls produce separate identities; existing expiry matrix proves omitted/null/finite expiry behavior. Run exact new nodes first, then affected MCP files only after parent allocates sole application-test slot. Before eventual review/PR run scripts/test-plan.py --base origin/main and its reported checks, workflow check, and full non-slow suite once when authorized; no publication or full CI in this slice.

**Plan review:** Pending independent clean-context technical review of this record and relevant sources.

**Approvals:** Pending parent-provided exact user approval evidence covering this bounded API change; existing authorization is reused without re-asking.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: api-review

What changes: expose existing optional caller message_id through MCP send. Compatibility risk: low; omission still follows existing generated-ID path. Verification: registered-schema and caller-surface retry/conflict/boundary tests. API checkpoint required for eventual PR.

## Implementation

- 2026-10-21: Verified GitHub main and fetched origin/main both resolve to a2726453323a363b0656ddf3d87a2d4b0d86937e. Created native worktree C:/Dev/rore/Pallium/build/relay-mcp-retry-identity on fix/relay-mcp-retry-identity. Primary dirty files and installed clone untouched.
- Source discovery complete; applicability is normal workflow because app/mcp/server.py is a protected red API path. No exemption claimed.
- Pallium work association list failed because no exact container_ref was injected. No identity was guessed and no association is claimed.

## Evidence

No application tests run. Parent owns test-slot allocation. Planning review/approval are the next actions.

## Recovery

Base revision a2726453323a363b0656ddf3d87a2d4b0d86937e; branch fix/relay-mcp-retry-identity; only this Work Record is added. Retain worktree for implementation and review. Roadmap contribution remains pending owner reconciliation; broader reliability tasks remain open.
