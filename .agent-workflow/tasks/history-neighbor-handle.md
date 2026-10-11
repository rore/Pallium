# Preserve an oversized following-message handle

<!-- agent-workflow:start -->
**Outcome:**
An agent can open a requested following message even when its text does not fit the current source expansion.

**Target:**
Pallium source-context HTTP and MCP expansion.

**Scope:**
Add a privacy-checked next-message reference for an oversized following neighbor, carry it through bounded MCP packaging, and add generic caller-facing regression coverage and concise documentation.

**Constraints:**
Keep search ranking, the 4000-character MCP cap, source visibility and forgetting, redaction, lookup lineage, and retrieval-not-use semantics unchanged. No paid evaluations, private transcript fixtures, dependencies, installed-service changes, or merging the separate PR278 investigation.

**Completion criteria:**
When a requested eligible following message exceeds the remaining expansion budget, the caller receives a fetchable reference without its text being recorded as delivered evidence. When that reference is opened, current authorization and forgetting are reapplied. Bounded multi-hop navigation works through the public MCP surface; normal fitting expansions, anchor continuation, and response-size/error contracts remain covered.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An agent can open a requested following message even when its text does not fit the current source expansion.","scope":"Add a privacy-checked next-message reference for an oversized following neighbor, carry it through bounded MCP packaging, and add generic caller-facing regression coverage and concise documentation.","constraints":"Keep search ranking, the 4000-character MCP cap, source visibility and forgetting, redaction, lookup lineage, and retrieval-not-use semantics unchanged. No paid evaluations, private transcript fixtures, dependencies, installed-service changes, or merging the separate PR278 investigation.","completion_criteria":"When a requested eligible following message exceeds the remaining expansion budget, the caller receives a fetchable reference without its text being recorded as delivered evidence. When that reference is opened, current authorization and forgetting are reapplied. Bounded multi-hop navigation works through the public MCP surface; normal fitting expansions, anchor continuation, and response-size/error contracts remain covered."}

**Risk:** High

**Complexity:** Moderate

**Reason:**
Caller-visible navigation contract crosses core/service.py (architecture-review), api/routes.py, api/schemas.py and app/mcp/server.py (api-review). Privacy gates and delivery accounting must remain intact.

**Discovery:**
Base 6be22d77, freshly fetched origin/main on 2026-10-11. get_source_context stops a side at its first oversized eligible neighbor and discards that ID. _bounded_expansion only sees selected neighbors. A read-only existing-evidence investigation demonstrated a 2362-character anchor followed by a 2787-character message exceeding 4000; this is a navigation capability failure, not proof of improved search recovery or downstream answers. Production callers are api/routes.py and app/mcp/client.py; reliable_pair_runner consumes the HTTP/MCP shape. Existing public-MCP integration and source-context visibility tests provide reusable isolated fixtures.

**Material assumptions:**
The existing bounded and authorized following window contains the next reference; do not scan beyond its 25-item limit. If the contract requires a new persistent cursor, authorization model, ranking change, or private corpus replay, stop and return to planning. A pointer is navigation metadata, not delivered message content or verified use.

**Plan:**
1. Invoke agent-workflow, establish this Work Record and classify the complete intended change before source edits; obtain clean-context technical plan review. Human approval of the narrow presented behavior is recorded below.
2. Add optional next_source_item_id for the first following neighbor rejected by the existing content budget, after existing eligibility checks. Carry it outside content items through the HTTP response and MCP formatter; retain it within the existing serialized cap, including anchor continuation. If MCP packaging itself removes a following item, retain the earliest removed following handle rather than skipping to a later service handle. If mandatory metadata cannot fit, return a bounded error, never silently remove the handle. No new endpoint, storage query, persistence schema, audit role or dependency. Keep normal content selection and evidence receipts unchanged: the pointer alone is navigation metadata, not delivered content. Document how to open it with existing parent_lookup_id and scope.
3. Add an anonymous red-before-green public-MCP regression using the demonstrated size class, then boundary/lifecycle cases. Target files: core/service.py, api/routes.py, api/schemas.py, app/mcp/server.py, tests/test_source_neighbor_handle_e2e.py, tests/test_mcp_server.py if needed, docs/session-history.md, and this Work Record. Reconcile roadmap prose only if needed; do not reopen the queued representation study or claim the older investigation passed.
4. Run focused tests, affected subsystem tests, whole-change test-plan and required full non-slow lane. Independent non-implementer result review covers API/architecture, privacy and evidence accounting. Prepare PR evidence; separate human result review and current CI/checkpoints remain merge gates. No live rollout.

**Verification plan:**
- When an eligible following message is over budget, the system shall return a fetchable handle without delivered-content credit -> public MCP-to-HTTP-to-service red/green test and persisted delivery receipt assertions.
- When traversing more than two messages, the system shall preserve scope and parent lineage and eventually open the oversized message -> generic four-hop public MCP test, including Unicode.
- When a handle target is forgotten, missing or no longer visible, the system shall deny opening it -> lifecycle tests through HTTP/MCP; hidden neighbors never appear in handle metadata.
- When before/after is zero, the thread ends, content fits exactly, or content is empty, the system shall preserve the bounded window and ordinary response -> boundary tests including max and over-max side bounds.
- When anchor content is continued or metadata cannot fit, the system shall keep the serialized cap and existing progress/error semantics -> MCP tests at minimum, normal and over-maximum budgets, stale revision and oversized anchor coverage.
- When the implementation is complete, the system shall preserve accepted unrelated behavior -> affected tests, test-plan-selected checks, full non-slow suite, independent review; no downstream task-effect claim.

**Plan review:**
Agent technical review: /root/neighbor_contract_review, 2026-10-11, base 6be22d77 and Work Record 82ddb441. Approved after clarifying serializer omissions and mandatory-handle cap behavior; clarification incorporated in step 2 before implementation. Reviewer inspected core, schema, HTTP, MCP and delivery consumers; High/Moderate and verification scope retained. No new audit role: a pointer is not message evidence.

**Approvals:**
Approved by user 2026-10-11: "ok, drive this"
Approval covers the presented next-message handle fix within existing limits and privacy rules, not live installation or unrelated retrieval changes.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Applicability and checkpoints

Normal isolated branch/PR workflow: intended runtime/API paths are outside the documentation-only allowlist. No protected behavior-contract edit is planned. API change is additive; architecture change carries a transient authorized navigation reference, not a new memory model. Technical plan review passed with the incorporated clarification; no source edits preceded review.

## Delivery boundaries

This is a new narrow correction from current main, separate from draft PR278. It does not establish complete recovery of the original historical question or resolve search discovery failures. No user environment or private evidence is changed.
