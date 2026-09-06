<!-- agent-workflow:start -->
**Outcome:**
`pallium_relay_recipients` always returns a usable bounded address-book page and exposes canonical exact/alias selectors, so agents neither lose discovery to the MCP response budget nor construct malformed alias handles.

**Target:**
Pallium Relay recipient discovery at the public MCP tool boundary.

**Scope:**
`app/mcp/server.py`; focused public MCP tests; `docs/agent-relay.md`; RW-013/RW-014 state in `roadmap/features/add-wake-first-relay-delivery.md`; this Work Record.

**Constraints:**
Keep the existing HTTP `/relay/sessions` list contract and Relay routing/storage unchanged. Preserve exact container/actor isolation. Add no dependency, no opaque cursor protocol, and no wall-clock test waits. The tool output must remain within 2,000 characters for every page.

**Completion criteria:**
(1) Empty, single, full, and over-budget recipient sets return a deterministic envelope with continuation metadata. (2) Every returned session includes a canonical exact selector and, when named, a canonical `runtime:@alias` selector. (3) Continuation exhausts the eligible set without duplicate items in a stable registry. (4) Invalid offsets and cross-scope/runtime/include-inactive combinations fail or filter safely through the public MCP surface. (5) The historical malformed-handle incident is corrected in the roadmap and live alias dogfood evidence is recorded.

**Risk:**
Elevated

**Complexity:**
Standard

**Reason:**
This changes a public MCP tool response shape and tool schema on the watch-listed MCP server surface, but does not change persistence, routing, HTTP schemas, or authorization. Multiple output-boundary and lifecycle cases require one coherent serializer plus caller-surface coverage.

**Discovery:**
The live MCP tool currently returns only `{"error":"relay response exceeds the response budget"}` for the scoped Codex registry. Historical context showed RW-013 was not a resolver mismatch: Claude reported `claude-code:claude_arch` without the required `@`, so it was parsed as an exact session selector. A current `codex:@relaydev` send delivered and received `alias-ok`, confirming alias resolution works.

**Material assumptions:**
The local recipient registry is small enough that fetching the existing scoped HTTP list before MCP-side paging is acceptable. Disproof: caller-surface measurement shows HTTP retrieval itself is a material latency/memory problem; if so, stop and plan API pagination separately. Offset continuation is a best-effort address-book traversal, not a snapshot; stable-registry exhaustion is the supported contract.

**Plan:**
Add one recipient-specific bounded serializer that sorts the already scoped list deterministically, adds canonical selector fields, and packs entries into a 2,000-character envelope with `offset`, `next_offset`, `has_more`, and `total_count`. Add a non-negative `offset` argument to the existing MCP tool and update its description. Drive the real MCP tool over the HTTP client fixture for boundary, continuation, selector, filtering, Unicode, invalid-offset, and lifecycle cases. Correct RW-013/RW-014 roadmap wording and the canonical documentation.

Key conventions: reuse `_json_text` and the existing MCP budget; do not add API pagination, dependencies, or a second tool.

Target files or classes: `app/mcp/server.py`; `tests/test_relay_mcp_tools.py`; `tests/test_mcp_server.py` only if a narrow pure-formatter boundary test is needed; `docs/agent-relay.md`; `roadmap/features/add-wake-first-relay-delivery.md`.

**Verification plan:**
Bounded deterministic address-book output and continuation → public MCP caller-surface E2E plus exact 2,000-character assertions. Canonical selector correctness and lifecycle → real register/name/transfer/close/send journey through HTTP/MCP surfaces. Isolation and filters → cross-container/actor, runtime, and include-inactive E2E. Regression floor → focused MCP/Relay suites, workflow/redline gates, and live installed tool witness after merge/reload.

**Plan review:**
Pending clean-context review.

**Approvals:**
—

**Exceptions:**
—

**State:** Draft
<!-- agent-workflow:end -->

## Implementation

- 2026-09-06: Reproduced RW-014 through the installed MCP tool and traced it to `_relay_text` falling through on oversized lists. Historical expansion proved RW-013 used a malformed alias selector; current live alias delivery/reply succeeded.

## Evidence

Pending.

## Result review

Pending.
