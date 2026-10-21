# MCP Relay sender retry identity

Canonical source: `roadmap/features/add-wake-first-relay-delivery.md`, sender retry identity checklist, at `a2726453323a363b0656ddf3d87a2d4b0d86937e`. Roadmap edits remain with the parent task's designated shared checkout.

<!-- agent-workflow:start -->
**Outcome:** MCP send callers can retry a committed send after response loss using one caller-supplied message identity without duplicating the durable message.

**Target:** Pallium Relay MCP send.

**Scope:** app/mcp/server.py, tests/test_relay_mcp_tools.py, tests/test_mcp_server.py, docs/agent-relay.md, and this Work Record.

**Constraints:** Preserve omitted-ID behavior and existing sender/payload/recipient/expiry conflict checks. No storage, schema, scheduler, native wake, installed environment, or response redesign changes. Preserve all protected behavior contracts.

**Completion criteria:** Same-ID retry after committed-send response loss yields one message and delivery through public reads; conflicting sender, payload, recipient or expiry rejects without mutation; omitted IDs still generate independent messages; empty and over-128 IDs reject, 1/128-character Unicode IDs succeed, and omitted/null expiry semantics remain intact.

**Requirement baseline:**
{"source":"roadmap/features/add-wake-first-relay-delivery.md@a2726453323a363b0656ddf3d87a2d4b0d86937e","outcome":"MCP send callers can retry a committed send after response loss using one caller-supplied message identity without duplicating the durable message.","scope":"app/mcp/server.py, tests/test_relay_mcp_tools.py, docs/agent-relay.md, and this Work Record.","constraints":"Preserve omitted-ID behavior and existing sender/payload/recipient/expiry conflict checks. No storage, schema, scheduler, native wake, installed environment, or response redesign changes. Preserve all protected behavior contracts.","completion_criteria":"Same-ID retry after committed-send response loss yields one message and delivery through public reads; conflicting sender, payload, recipient or expiry rejects without mutation; omitted IDs still generate independent messages; empty and over-128 IDs reject, 1/128-character Unicode IDs succeed, and omitted/null expiry semantics remain intact."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Behavior changes:**
[{"target":"task-context.scope","classification":"equivalent","before":"app/mcp/server.py, tests/test_relay_mcp_tools.py, docs/agent-relay.md, and this Work Record.","after":"app/mcp/server.py, tests/test_relay_mcp_tools.py, tests/test_mcp_server.py, docs/agent-relay.md, and this Work Record.","reason":"Add one expected message_id=None field to the existing exact client-forwarding assertion; preserve every previous payload/scope assertion and unchanged externally omitted-ID behavior."}]

**Risk:** High

**Complexity:** Simple

**Reason:** app/mcp/server.py is a red API contract surface requiring api-review. One optional argument exposes an existing client/storage contract; no new storage behavior or dependency.

**Discovery:** MCP tool omits message_id although its docstring already describes existing-ID expiry. PalliumMcpClient.relay_send already accepts optional message_id, generates a UUID when absent, and passes explicit identities unchanged. RelaySendRequest accepts 1–128 characters. SQLite relay_send matches sender identity, payload, recipient selector, redaction, parent, and supplied expiry before returning the existing status. tests/test_relay_mcp_tools.py already provides registered FastMCP call_tool plus real HTTP ASGI/storage fixtures and public status/turn reads. Existing callers omit the new argument and need no edits. No behavior_contracts path changes.

**Material assumptions:** Existing client/storage identity semantics fully implement the required contract. If caller-surface regression exposes a defect beyond tool forwarding, return to planning rather than extending persistence scope. No installed or native qualification is needed to prove this repository contract.

**Plan:** Add optional nullable message_id with Field(min_length=1, max_length=128) to registered pallium_relay_send and forward it unchanged to relay_send. Briefly document generating/reusing one ID for identical retries after uncertain response; omitted ID remains a new send. Extend existing FastMCP/ASGI tests: commit via real HTTP then suppress its response, retry same ID, inspect public status and claim/ACK lifecycle; parameterize conflicts and identity boundaries, and assert omitted IDs remain independent. Reuse existing expiry fixtures and error helpers. Stop on scope expansion, conflicting baseline, or unmet review/approval gate. No production code edits until technical plan review and exact-scope human approval are recorded.

**Verification plan:** Registered schema asserts optional nullable 1–128-character string. Caller-surface fault test drives FastMCP call_tool → client → HTTP → SQLite, loses the committed response, retries, observes one message/delivery via status and turn, ACKs, and observes no second delivery. Sender/payload/recipient/expiry conflicts assert HTTP 409 and unchanged original status/inboxes. Boundary cases include empty/129 rejection and 1/128 Unicode acceptance. Omitted/null ID calls produce separate identities; existing expiry matrix proves omitted/null/finite expiry behavior. Run exact new nodes first, then affected MCP files only after parent allocates sole application-test slot. Before eventual review/PR run scripts/test-plan.py --base origin/main and its reported checks, workflow check, and full non-slow suite once when authorized; no publication or full CI in this slice.

**Plan review:** Agent technical review: /root/sender_api_plan_review, 2026-10-21, GO with no blocking findings after reading this record at 55d8fc61 plus server registration, client relay_send/_post_or_error, HTTP schema/routes, core Relay.send, SQLite relay_send/_expiry_matches, MCP expiry/lifecycle fixtures and client forwarding tests. Reviewer requires send help to allow identical same-supplied-ID retry after uncertain response instead of contradictory blanket resend prohibition; accepted.

**Approvals:** Approved by user 2026-10-21: "So this is all regarding reliability. So if there are things to research more or fix here, then they should be part of what we're doing." Root supplied request_source_item_id c3ecdd91-903f-4c6c-a011-f23a7791571a and confirmed this followed its reviewed recommendation to expose existing stable-ID MCP support. Subsequent user scope confirmation: "This all should go as tasks we need to fix for reliability" (1d8902c1-e762-4086-b569-42c305faf58e). These quotes authorize the reliability fix at scope level; root adopts the additive optional message_id plan without storage or contract weakening. No claim of literal field-specific user wording is made.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Checkpoint: api-review

What changes: expose existing optional caller message_id through MCP send. Compatibility risk: low; omission still follows existing generated-ID path. Verification: registered-schema and caller-surface retry/conflict/boundary tests. API checkpoint required for eventual PR.

## Implementation

- 2026-10-21: Verified GitHub main and fetched origin/main both resolve to a2726453323a363b0656ddf3d87a2d4b0d86937e. Created native worktree C:/Dev/rore/Pallium/build/relay-mcp-retry-identity on fix/relay-mcp-retry-identity. Primary dirty files and installed clone untouched.
- Source discovery complete; applicability is normal workflow because app/mcp/server.py is a protected red API path. No exemption claimed.
- Pallium work association list failed because no exact container_ref was injected. No identity was guessed and no association is claimed.
- Plan review accepted; additive optional message_id and forwarding implemented without client/storage changes. Tool help and docs now describe safe same-identity retry after uncertain response.
- Added 16 parameter cases in the existing FastMCP/ASGI test file: registered schema, four expiry variants with post-commit response loss and pending/delivered retries, five identity conflicts, and six Unicode/boundary/omitted/null cases. Fault injection wraps actual ASGI transport; client HTTP/error logic remains intact.
- Focused execution found two new test setup mistakes (turn response nests endpoint under session; no /relay/recipients route); corrected to use actual registration responses. Affected coverage found exact help capitalization and mocked kwargs expectations; retained the qualified Do not resend caution and added expected message_id=None without weakening assertions. No client/storage changes were needed.

## Evidence

Application-test slot was allocated after PR325's first cohort and released immediately after owned root 41044 exited at 2026-10-21T08:25:34.677Z. Existing isolated runtime C:/Users/I347041/AppData/Local/Temp/po-7o13uuj6/v/Scripts/python.exe; child-only environment scrub/private short Temp profile, assertions enabled, retained-process-handle cap/drain runner. No dependency or installed-environment changes.

- AST parsing of app/mcp/server.py and tests/test_relay_mcp_tools.py passed using the existing development Python; git diff --check passed. Neither check imports the application or consumes the application-test slot.
- All 16 new cases passed with evidence reuse: schema (new-cases-short, head 0d247ecf); response-loss four expiry variants (remaining15, head 36037600); conflict/boundary/generated-ID eleven cases (remaining11, head 2e3bc1bb, runner exit 0). Later changes affect only test setup/assertion bookkeeping and help punctuation/capitalization; message identity forwarding is unchanged.
- All 337 existing cases in tests/test_relay_mcp_tools.py, tests/test_mcp_server.py, tests/test_mcp_client.py and tests/test_mcp_integration.py passed: 217 in affected, one in affected-remaining, 119 in affected-final (head 3bcfc1c5). Passing nodes were explicitly deselected on continuation. New 16 were excluded from the affected runs. Logs, JUnit, source/lock hashes, private-environment recipes and process receipts are retained under build/retry-identity/ in this worktree.
- Failure receipts are preserved: new-cases failed before any test body because sandbox temporary-directory setup/CIM snapshot were unavailable; new-cases-short and remaining15 exposed the two test setup errors; affected and affected-remaining exposed exact existing help/mock expectations. Each concrete failure was corrected, with no blanket rerun and no expectation weakening.
- Final affected runner: exit 0, uncapped, root exit verified, streams complete, direct-child snapshot empty, clean worktree and unchanged source/lock hashes. This is a direct-child snapshot, not universal/reparented-descendant proof.
- Actual import-linter boundary backend passed; fresh Redline/workflow evidence generated. Workflow status advisory solely for the eventual PR api-review checkpoint label/CODEOWNER evidence. Baseline, relationships, High approval, independent plan review and boundary/behavior-contract predicates passed; protected test paths are unchanged.
- Selector reports full lane: python -m pytest tests/ -x -q. Full non-slow execution is not yet authorized; prepare exact manifest and obtain parent review before running. No CI/publication/installed qualification has run.

## Result review

Agent technical review: /root/sender_api_plan_review reviewed implementation 0d247ecf read-only with no code/test-design blockers; execution receipts and later test-only corrections were supplied for independent result review. Final execution-evidence review is pending. Full-suite evidence remains outstanding, so no final readiness claim is made.

## Recovery

Base revision a2726453323a363b0656ddf3d87a2d4b0d86937e; branch fix/relay-mcp-retry-identity; latest application/test revision 3bcfc1c5670fe9b6eba23220b9e8c6d608721683. Production forwarding, documentation and focused/affected verification are complete. Next: independent evidence review and parent review of the exact selector-required full-suite manifest; do not start full execution without that review. Retain worktree for verification and review. Roadmap contribution remains pending owner reconciliation; broader reliability tasks remain open.
