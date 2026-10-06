# Exact Relay discovery lifecycle

<!-- agent-workflow:start -->
**Outcome:** Exact Relay session lookup returns an existing session with lifecycle, health and last-active metadata instead of hiding it because it is inactive.
**Target:** Scoped Relay recipient discovery through HTTP and MCP.
**Scope:** storage/sqlite_relay.py exact session lookup; app/mcp/server.py tool description; existing Relay HTTP/MCP lifecycle tests; docs/agent-relay.md and roadmap/features/add-global-relay-recipient-discovery.md.
**Constraints:** Preserve container isolation, runtime/session identity, existing response schema, bounded output and pagination, broad recent-only listing defaults, alias ownership, send eligibility and all claim/wake behavior. No live state mutation or new API/configuration.
**Completion criteria:** Exact scoped lookup returns recent, dormant, closed and unreachable matches with status and last_seen_at; absent or wrong-scope matches stay empty; broad default listing and explicit include_inactive listing retain their behavior; discovery is read-only and closed/unreachable send restrictions remain enforced.
**Requirement baseline:** {"source":"user:a97a34a4-22a2-4d82-8a77-ab4b93910c6e","outcome":"Exact Relay session lookup returns an existing session with lifecycle, health and last-active metadata instead of hiding it because it is inactive.","scope":"storage/sqlite_relay.py exact session lookup; app/mcp/server.py tool description; existing Relay HTTP/MCP lifecycle tests; docs/agent-relay.md and roadmap/features/add-global-relay-recipient-discovery.md.","constraints":"Preserve container isolation, runtime/session identity, existing response schema, bounded output and pagination, broad recent-only listing defaults, alias ownership, send eligibility and all claim/wake behavior. No live state mutation or new API/configuration.","completion_criteria":"Exact scoped lookup returns recent, dormant, closed and unreachable matches with status and last_seen_at; absent or wrong-scope matches stay empty; broad default listing and explicit include_inactive listing retain their behavior; discovery is read-only and closed/unreachable send restrictions remain enforced."}
**Risk:** High
**Complexity:** Simple
**Reason:** Existing public discovery semantics and red-zone storage/API files change; no persistence schema or write path changes are intended.
**Discovery:** relay_list_sessions applies the broad active/24-hour filter to exact identity lookup. Global exact discovery already includes all lifecycle states. Existing MCP tests explicitly assert hidden dormant/closed exact matches. Alias routing does not use the recency filter. Current Dev2 identity/alias exists; the historical empty lookup cause is not proven.
**Material assumptions:** Existing session views contain all required status/time fields; if false, return to planning before adding a schema. Existing read query is sufficient; no new index, migration or state update is justified.
**Plan:** Invoke agent-workflow and classify before code edits. Independent technical review of the narrow contract change; reproduce the current exact-lookup omission through caller-surface tests, remove only the exact-lookup activity filter, update the tool description and documentation. Preserve broad-list behavior and sender scope. Run focused/affected checks then selector-required full once; independent result review before publication.
**Verification plan:** Exercise exact recent/dormant/closed/unreachable identities through HTTP and MCP, cutoff boundary, wrong scope/runtime, absent identity, Unicode, pagination/output budget, read-only behavior and unchanged send rejection. Reuse existing coverage where unchanged; extend the existing lifecycle test rather than add infrastructure. Run scripts/test-plan.py against origin/main and its reported checks, import boundaries and workflow checks.
**Plan review:** Pending independent clean-context technical review before implementation.
**Approvals:** Approved by user 2026-10-06: "so let's drive this fix", following the explicit requirement that lookup always return an existing session with status and last active. Source user:a97a34a4-22a2-4d82-8a77-ab4b93910c6e; requirement user:d671c669-d5eb-4920-a8fe-abf5ae2bc55c.
**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation
Applicability: normal workflow; production storage/API paths are outside the documentation-only exemption. No production edit before independent plan review. Root owns roadmap alignment and release.

## Evidence
Read-only diagnosis reviewed scoped/global discovery, alias routing and existing lifecycle regression assertions. No evidence establishes alias deletion in the reported Dev2 incident.
