# Explicit memory provenance integrity

Branch: `codex/explicit-memory-provenance`

<!-- agent-workflow:start -->
**Outcome:**
Every agent-created memory is stored under a deliberate canonical scope with complete creation provenance, and operators can see who/which agent/session created it.

**Target:**
Pallium explicit memory-write HTTP/MCP path and Claude/Codex integration scope headers.

**Scope:**
Remember, supersede, and record-outcome creation paths; shared explicit-container validation; MCP context forwarding; dashboard provenance display; packaged Claude/Codex guidance and hooks; HTTP/MCP/integration E2E coverage.

**Constraints:**
Do not add authorization, claim the supplied identity is authenticated, add a container registry, reject valid generated `path:` identifiers, alter retrieval/accessibility ranking, add a mutation-audit subsystem, or modify the local VBS launcher. Correction/forget mutation authorship is explicitly deferred because existing storage has no immutable per-operation provenance model.

**Completion criteria:**
Agent-created remember, supersede, and outcome rows require non-empty container, actor, thread/session, agent, and visibility context; raw absolute Windows/POSIX/UNC paths fail before persistence while canonical `git:`, `repo:`, and generated `path:` identifiers remain valid; thread and agent provenance land in the existing origin columns and visibility lands on the memory; the dashboard identifies creator actor/agent/session; Claude and Codex injected scope headers provide the exact values agents must pass; missing/invalid context creates no memory or index entry; all behavior is covered through the public HTTP and MCP surfaces without changing retrieval ranking.

**Risk:**
High

**Complexity:**
Moderate

**Reason:**
Redline classifies the request-model and route changes as API contract surfaces and the service invariant as architecture red; deliberate scope/identity validation is security-sensitive. Several callers and integrations change, but existing persistence columns avoid a schema migration.

**Discovery:**
The incident row was created through `pallium_remember` with a raw Windows cwd and NULL actor/session/agent provenance. `memory_objects` already stores actor, visibility, `origin_session_id`, and `origin_agent_id`; `mark_memory_origin` already writes the latter two. MCP resolves container/thread/actor/visibility but does not accept agent identity and does not pass thread/agent into remember/supersede/outcome provenance. The HTTP schemas make all creation provenance optional; service canonicalization accepts arbitrary opaque strings, including raw absolute paths. Claude/Codex hooks already derive the canonical container, session, actor, and static agent identity, but injected scope headers expose only container/thread. Dashboard memory rows omit all creation provenance except visibility. Correct/forget have reasons/tombstones but no immutable mutator provenance; overloading creation fields or reason text would be false auditability.

**Material assumptions:**
- Existing origin columns are sufficient for creation provenance; disprove if a public read cannot retrieve them, then expose the existing columns rather than change storage.
- Each hook invocation can supply container, session, actor, and agent to the injected header; disprove if a supported runtime lacks one, then fail explicit creation visibly instead of inventing `unknown`.
- Requiring provenance on the agent-explicit creation endpoints is compatible with supported integrations after refresh; disprove via repo callers/tests, then update those callers in this PR without weakening the invariant.
- Mutation authorship is not necessary to fix this creation incident; if immutable correction/forget attribution is required, stop and plan a separate persistence-reviewed event model.

**Plan:**
1. Add one shared core validator beside `canonicalize_container_ref` that rejects only raw absolute filesystem paths and blank explicit identifiers, preserving generated `path:` and other opaque schemes.
2. Make creation provenance deliberate at the HTTP/service boundary for remember, supersede, and record-outcome: require container, actor, thread/session, agent, and visibility; reuse the existing origin columns; preserve the existing public field names where possible and reject missing values before any row/index write.
3. Extend MCP context/tool/client forwarding with explicit agent identity and map the active thread to creation-session provenance. Return compact validation errors through the existing client error shape.
4. Extend Claude/Codex scope headers and packaged guidance to expose/use exact container, thread, actor, agent, and private visibility, preserving injection budgets and control-character rejection.
5. Expose existing creation provenance in the dashboard memory response/detail metadata.
6. Add boundary and full-lifecycle HTTP/MCP/integration E2E tests, run focused and full checks, obtain clean-context result review, align docs/roadmap if status changes, then push/PR/monitor/fix/merge. Refresh installed integrations and restart/health-check the unchanged VBS-launched local service after merge.

Key conventions: `core.container_ref` remains the sole container-normalization source; `actor_ref` is the human/user identity while origin agent is the producing agent; provenance is attribution, not authentication; retrieval alone never changes accessibility state. Target files: `core/container_ref.py`, `core/service.py`, `api/schemas.py`, `api/routes.py`, `app/mcp/context.py`, `app/mcp/client.py`, `app/mcp/server.py`, `app/dashboard.py`, `app/dashboard.html`, Claude/Codex hook/guidance files, and focused tests. Stop if implementation requires a storage schema change, a new authorization rule, or an invented fallback identity.

**Verification plan:**
- When any required creation-provenance field is missing/blank, HTTP and MCP shall reject the write and persist no memory/index → HTTP/MCP E2E count-before/count-after tests.
- When a raw Windows, POSIX, or UNC path is supplied, all three creation operations shall reject it; when canonical `git:`, `repo:`, generated `path:`, mixed-case GitHub, or Unicode opaque scopes are supplied, valid forms shall persist canonically/unchanged as defined → shared-validator boundary tests plus HTTP E2E.
- When a valid agent creation succeeds, memory actor/visibility and existing origin session/agent columns shall match the supplied scope → HTTP/MCP lifecycle tests using the dashboard/read surface.
- When the dashboard returns and expands an explicit memory, it shall display actor, agent, and session provenance in plain labels → dashboard API test and browser/DOM validation.
- When Claude/Codex inject scope with or without memory blocks, it shall include safe exact container/thread/actor/agent/visibility values within the existing character budget and reject control-character injection → integration boundary tests.
- When explicit memories are created, corrected, superseded, forgotten, queried, and outcomes recorded, lifecycle/conflict/idempotence/Unicode/max-boundary behavior shall remain intact and retrieval ranking/accessibility shall not be updated merely by write/retrieval → updated W3 E2E plus focused regression suites.
- When delivery completes, workflow/redline/import checks and CI shall be green; installed integrations shall match merged sources; local `/health` shall report `status=ok` and `embedding_provider_ok=true` after VBS service restart.

**Plan review:**
Pending clean-context High-risk plan review.

**Approvals:**
Pending post-review human approval.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Checkpoint: explicit-memory-provenance

What is changing: The explicit memory creation API will reject incomplete or raw-path scope/provenance, supported MCP integrations will supply complete provenance, and the dashboard will expose stored authorship.

Why: Agent-created memories can currently be written into an accidental scope with no attributable actor, agent, or session.

Affected contract / model / boundary: HTTP request validation, MCP tool contracts, core explicit-write invariant, and operator-facing dashboard response.

Compatibility / migration risk: Medium — supported clients must provide fields that were optional; existing rows and schema remain readable and unchanged.

Verification plan: Public HTTP/MCP no-partial-write tests, integration scope-header tests, existing-column persistence assertions, dashboard DOM validation, full CI, and live post-merge service health.

## Plan review

Pending.
