<!-- agent-workflow:start -->
**Outcome:** Inventory accepts a bounded Desktop tools/list containing unrelated dictionary schemas whose top-level form is array, union, or omits type, while the intended owner tool remains strictly checked before any owner action.

**Target:** Finite Codex Desktop inventory bridge for the unloaded Relay payload trial.

**Scope:** Remove only the blanket inputSchema.type == object rejection in app/codex_bridge_pipe.py; update caller-visible inventory tests in tests/test_codex_bridge_pipe.py and one adjacent design statement in docs/designs/codex-mcp-desktop-bridge.md. No other code, contract, or live-state change.

**Constraints:** Preserve list/frame bounds, per-tool dictionary/name/uniqueness checks, all native response and authority rejections, and the unchanged strict _owner_tool_schema_valid check before owner tools/call. Do not inspect or log private catalog contents, infer the live offending tool, add diagnostics, retry a live action, or change settings.

**Completion criteria:** A caller tools/list response with otherwise valid unrelated array, union, or missing-type dictionary inputSchema passes before inventory; non-dictionary schema still fails; malformed intended send_message_to_thread descriptor never causes an owner tools/call. The exact finite trial remains unqualified until a target turn and hook ACK/trace are observed live.

**Requirement baseline:**
{"source":"root task assignment after direct user simplify steering 8516b0dc-ed87-4ce4-8e76-902999a0dec8","outcome":"Inventory accepts a bounded Desktop tools/list containing unrelated dictionary schemas whose top-level form is array, union, or omits type, while the intended owner tool remains strictly checked before any owner action.","scope":"Remove only the blanket inputSchema.type == object rejection in app/codex_bridge_pipe.py; update caller-visible inventory tests in tests/test_codex_bridge_pipe.py and one adjacent design statement in docs/designs/codex-mcp-desktop-bridge.md. No other code, contract, or live-state change.","constraints":"Preserve list/frame bounds, per-tool dictionary/name/uniqueness checks, all native response and authority rejections, and the unchanged strict _owner_tool_schema_valid check before owner tools/call. Do not inspect or log private catalog contents, infer the live offending tool, add diagnostics, retry a live action, or change settings.","completion_criteria":"A caller tools/list response with otherwise valid unrelated array, union, or missing-type dictionary inputSchema passes before inventory; non-dictionary schema still fails; malformed intended send_message_to_thread descriptor never causes an owner tools/call. The exact finite trial remains unqualified until a target turn and hook ACK/trace are observed live."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** The runtime bridge is a watched app path and this removes one restrictive validation predicate at the native boundary. The owner-tool action guard and protected contracts remain unchanged; caller tests and design text are affected.

**Discovery:** Live inventory failed at fixed stage before-validate-schema-object. That proves one advertised dictionary inputSchema lacked top-level type object, but does not identify its tool or exact shape. Desktop's installed static tools/list mapper passes inputSchema through. app/codex_bridge_pipe.py applies the blanket predicate before the separate exact owner descriptor guard.

**Material assumptions:** The blanket predicate is unnecessary for inventory observation and does not guard the later owner action; disproved if another consumer relies on every catalog schema being object, in which case stop and return to planning. The existing _owner_tool_schema_valid remains mandatory; disproved by a caller test that reaches tools/call with a malformed owner descriptor, in which case stop.

**Plan:** First write caller-visible red tests for unrelated array/union/missing-type dictionary schemas and malformed owner descriptor with zero tools/call; retain non-dictionary failure. After independent plan review, delete only the three-line global type-object predicate and adjust the incidental prior schema-object rejection test. Add one sentence that unrelated dictionary schemas are opaque inventory data. Run exact nodes, affected bridge tests, selector-required checks, then independent result review. Do not alter the owner guard, native authority, retry, or live operator flow.

**Verification plan:** When tools/list has a bounded unrelated dictionary schema with array, union, or absent type, before inventory shall succeed -> actual private-pipe caller test. When a schema is non-dictionary, native-failed shall remain -> existing caller case. When the intended owner descriptor is malformed, no tools/call shall occur -> finite-trial caller test. Whole-change selector and required full non-slow lane run once after coherent change.

**Plan review:** Agent technical review: /root/service_handoff_security read this exact pre-edit Work Record and gave GO on the scoped deletion, retained outer checks and strict owner guard, and caller regression plan. This is technical review, not human authorization.

**Approvals:** Direct user approval relayed by root on 2026-10-01: "i approve", answering: "The smallest proposed fix removes the schema restriction for tools we never call, while keeping strict validation of the send tool. Do you approve that exact change and its regression tests?" This approves the exact before/after and tests; the reviewer GO is separate technical evidence.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Work Record and risk classification established before production or test edits. Independent reviewer gave technical GO; direct user then approved the exact behavior change and regression tests. Three actual private-pipe caller cases for unrelated array, union, and missing-type dictionary schemas failed before the production edit at `before-validate-schema-object`. Deleting only that blanket predicate made those and retained rejection cases pass (16). The owner-action caller test now includes malformed intended descriptor with zero `tools/call` (9 passed). A short adjacent design statement clarifies that unrelated dictionary schemas are opaque.

## Evidence

Original controlled trial: `.agent-workflow/tasks/codex-unloaded-payload-trial.md`. Canonical roadmap: `roadmap/features/add-wake-first-relay-delivery.md`. Live stage was content-free; no private catalog was read.

## Result review

Pending implementation and verification.
