<!-- agent-workflow:start -->
**Outcome:** A caller that knows a Relay session reference can resolve that recipient directly instead of scanning every session page.

**Target:** Pallium Relay.

**Scope:** Existing Relay session-list storage, service, HTTP, MCP paths, focused tests, and required Relay docs/roadmap alignment; no new endpoint or alias mechanism.

**Constraints:** Preserve container authorization, existing pagination and unfiltered behavior; no schema, service-install, or search-quality changes.

**Completion criteria:** When `session_ref` is supplied, session listing returns only the matching in-scope session or no rows; omission preserves current paginated results; caller-surface tests cover match, miss, scope isolation, and compatibility.

**Risk:** High

**Complexity:** Moderate

**Reason:** Intended scope touches red-zone API contracts and core service orchestration. The behavior is narrow but crosses storage, service, HTTP, and MCP caller surfaces.

**Discovery:** The existing flow is `storage/sqlite_relay.py::relay_list_sessions` → `core/relay.py::RelayService.list_sessions` → `api/routes.py::relay_sessions` → `app/mcp/client.py::relay_recipients` → `app/mcp/server.py::pallium_relay_recipients`. `relay_sessions` are unique by `(container_ref, runtime, session_ref)`, and `_relay_session` already performs that exact scoped lookup. Therefore exact zero-or-one resolution must require `runtime` with `session_ref`. The MCP layer applies its small output page only after the API returns rows. No schema change or new import is needed. Redline verdict: API_CHANGE/RED for `api/routes.py`, api-review required; other production paths are watch/gray, tests blue; no boundary risk.

**Material assumptions:** Existing clients omit `session_ref` and retain identical behavior; disprove with focused compatibility tests, then return to planning. Callers needing exact resolution know the runtime because storage does not define `session_ref` as globally unique; if that proves false, return to planning rather than choose an ambiguous row.

**Plan:** 1. Thread optional `session_ref` through `app/mcp/server.py`, `app/mcp/client.py`, `api/routes.py`, and `core/relay.py`. Validate it with the existing `_opaque` boundary and reject exact lookup without `runtime`. 2. In `storage/sqlite_relay.py`, reuse `_relay_session` for exact scoped lookup, then apply the same active/recent filter unless `include_inactive` is true; leave the existing query unchanged when absent. 3. Extend the existing MCP caller-surface journey for exact match, miss, dormant inclusion, runtime requirement, and scope isolation; extend the MCP client forwarding assertion. Stop if response shape, unfiltered order/pagination, container authorization, or composite identity semantics would change. Key conventions: no new endpoint, schema, helper, dependency, alias lookup, or dashboard feature. Target files are the five production files above, `tests/test_relay_mcp_tools.py`, `tests/test_mcp_client.py`, and this Work Record.

**Verification plan:** Exact lookup seeds identical refs across runtimes and containers; requested composite returns one, ref existing only outside scope returns zero → real FastMCP→ASGI journey with error-preserving GET binding. Recent active and an active session exactly at the recency cutoff return; a session just before the cutoff and a closed session stay hidden unless `include_inactive`; exact offsets 0/1 remain truthful → same journey. Empty, surrounding-whitespace, control-character, 255/256-character, Unicode, invalid-runtime, and omitted-runtime inputs assert the registered tool's structured success/error contract → same journey. Omitted filter preserves existing deterministic pagination → existing journey. MCP client forwards the optional value exactly → focused client test. Final diff obeys workflow/redline and the affected suite remains green → local checks plus affected tests, then full `tests/ -x` once before review.

**Plan review:** Clean-context Astra review in § Plan review — PASS after all findings were incorporated.

**Approvals:** Approved by user 2026-09-12: "Bugs should be fixed immediately"

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Task context and provisional classification were recorded before code inspection. Discovery traced the existing storage-to-MCP path, redline classified the API change, and the reviewed plan is ready to implement.

Implemented the optional exact session_ref filter through storage, core, HTTP, MCP client, and MCP tool boundaries. Exact lookup requires runtime, reuses _relay_session, preserves container and recent/inactive filtering, and leaves the unfiltered query unchanged. Added the reviewed composite-identity, scope, lifecycle, offset, input-boundary, Unicode, and client-forwarding coverage. Final review found no code defect and required stale roadmap/docs reconciliation; the item and public usage note now match the shipped contract.

## Plan review

Initial clean-context Astra review required explicit composite-identity and outside-scope fixtures; complete exact-input boundary validation; exact cutoff/just-before-cutoff/closed lifecycle coverage; exact offsets; and a tool-description statement that runtime is required. The verification plan now includes each item. Final re-review: PASS.

## Evidence

- Focused exact contract: 2 passed in 1.13s.
- Affected Relay/MCP/cross-container files: 195 passed in 45.37s.
- Full suite with complete pinned extras: 4861 passed, 33 skipped, 215 deselected, 2 xfailed in 765.21s.
- The first full-suite invocation omitted the vector extra and stopped at collection with missing numpy; rerunning with the repository's complete pinned extras passed.

## Result review

Pending.
