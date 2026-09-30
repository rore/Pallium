<!-- agent-workflow:start -->
**Outcome:** An agent can discover candidate Relay recipients through MCP when the target container is unknown, then choose an exact address with clear safety guidance.

**Target:** Pallium Relay.

**Scope:** A read-only, bounded service-global MCP recipient lookup; its supporting existing local HTTP listing/filter, caller tests, and agent-facing guidance.

**Constraints:** Keep `pallium_relay_recipients` container-local; do not change send, broadcast, History, memory, wake, or authorization semantics. Do not infer a recipient from a title or pick among ambiguous identities. Keep responses compact and secret-free.

**Completion criteria:** When a target container is unknown, the MCP caller can list recent candidates across containers and filter by an exact runtime/session reference without scanning every page; pages give truthful continuation. Duplicate references, inactive/closed sessions, empty results, invalid inputs, Unicode, and transport errors are explicit. Agent guidance explains verification and exact-selector use. Focused and selected validation plus PR review pass.

**Requirement baseline:**
{"source":"user source item 29664dea-baa0-4ae8-bc7b-b29cf14d512d and immediately preceding Pelican exchange","outcome":"An agent can discover candidate Relay recipients through MCP when the target container is unknown, then choose an exact address with clear safety guidance.","scope":"A read-only, bounded service-global MCP recipient lookup; its supporting existing local HTTP listing/filter, caller tests, and agent-facing guidance.","constraints":"Keep `pallium_relay_recipients` container-local; do not change send, broadcast, History, memory, wake, or authorization semantics. Do not infer a recipient from a title or pick among ambiguous identities. Keep responses compact and secret-free.","completion_criteria":"When a target container is unknown, the MCP caller can list recent candidates across containers and filter by an exact runtime/session reference without scanning every page; pages give truthful continuation. Duplicate references, inactive/closed sessions, empty results, invalid inputs, Unicode, and transport errors are explicit. Agent guidance explains verification and exact-selector use. Focused and selected validation plus PR review pass."}

**Risk:** High

**Complexity:** Moderate

**Reason:** `app/mcp/server.py` is a red API-contract surface, and service-global session metadata widens agent-visible discovery. Several caller and guidance surfaces need synchronized validation.

**Discovery:** Existing `pallium_relay_recipients` resolves the injected container and calls scoped `/relay/sessions`; it must remain scoped. `GET /dashboard/api/relay/sessions` already lists service-global local Relay sessions but lacks exact `session_ref` filtering and carries Dashboard-only rich fields. Its collision calculation scans broader sessions/deliveries, so MCP needs a compact query path that skips it. Exact session identity is `(container_ref, runtime, session_ref)`, not runtime/session_ref alone; a global runtime/session_ref filter can return multiple containers. Existing indexes lead with `container_ref`. Three bundled integration references currently require an independently known target container and must be corrected together.

**Material assumptions:** The unauthenticated installed Pallium service is trusted-local (`docs/context/operations.md`; `docs/dashboard.md`); the new global MCP tool must reject non-loopback service URLs and non-loopback network MCP binds, rather than rely on this assumption silently. Global result metadata is advisory until the caller verifies target identity; if no trustworthy match exists, ask the user or target for an address.

**Plan:** First invoke Agent Workflow to create this Work Record and classify risk before any production edit (done). In `app/dashboard.py`, add optional exact `session_ref` filtering (require runtime, mirror existing 32/255 limits) and a compact projection that selects only identity/health/title hint fields, skipping activation/collision work. Default recent candidate listing excludes dormant/closed; exact runtime/session_ref lookup searches all lifecycle states and returns all matching containers. In `app/mcp/client.py` and `app/mcp/server.py`, add a dedicated read-only global-discovery tool with local-service/bind checks, fixed allowlist/error shape, 2,000-character page budget, truthful count and offset advancing by emitted rows, and no injected sender-container filter or automatic recipient selection. Query order is deterministic; document that offset pages can shift under concurrent registration. Add a global `(runtime, session_ref)` SQLite index in `storage/sqlite_schema.py`: representative 10,000-row `EXPLAIN QUERY PLAN` showed the current indexes scan and this index searches. Update `docs/agent-relay.md`, three synchronized integration reference files, and guidance tests. Add MCP-to-ASGI and HTTP caller tests. Stop on authorization or performance regression.

**Verification plan:** Unknown-container discovery and exact filtering across containers/runtimes, including duplicate native IDs and recent/dormant/closed state → MCP-to-ASGI and HTTP caller E2E. Bounded pagination, Unicode, malformed/oversized input, missing runtime, empty and transport error → focused MCP tests. Loopback enforcement, fixed secret-free projection, unchanged scoped listing, and no send side effects → caller E2E/state reads. Representative-scale `EXPLAIN QUERY PLAN` and timing → index decision recorded before code review. Guidance stays synchronized and describes safe use/offset instability → guidance tests. Full change → `python scripts/test-plan.py --base origin/main`, reported checks, independent result review, CI.

**Plan review:** Agent technical review: `/root/global_lookup_plan_review`, independent gpt-6-sol high at base revision `0a42331514287f799ff852b67b369072b2682fe8`, inspected `app/dashboard.py`, MCP context/server/client, schema indexes, docs and tests. Findings: enforce local-only boundary; avoid collision/rich Dashboard projection; all-container ambiguity, lifecycle and pagination truth; filter validation and representative query-plan check. This revision incorporates every material finding; reviewer confirmed the refined design resolves them. Separate human consent recorded below.

**Approvals:** Approved by user 2026-09-30T09:03Z: "approve" (direct answer to the reviewed High-risk MCP plan presented in the owning chat).

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

Source request: user item `29664dea-baa0-4ae8-bc7b-b29cf14d512d` on 2026-09-30. The Work Record and approval preceded production edits.

## Implementation

Target files/classes: `app/dashboard.py::dashboard_relay_sessions`,
`app/mcp/client.py::PalliumMcpClient`, `app/mcp/server.py::create_server`,
`storage/sqlite_schema.py::SQLiteSchemaMixin`, HTTP/MCP/schema/guidance tests,
`docs/agent-relay.md`, the Codex/Claude/OpenCode Pallium skill references and
trigger lines, the two integration tool tables, and the Minimap roadmap item/board.

The existing Dashboard listing was reused with a compact path so MCP never
receives activation or collision details and does not run their broader query.
The MCP tool applies its own fixed projection and character budget. A 10,000-row
representative SQLite plan changed from `SCAN relay_sessions` to an indexed
`SEARCH` with `(runtime, session_ref)`, justifying the new schema index.
The trusted-local constraint is enforced at MCP service URL/bind, not assumed
from caller-supplied scope. The sender's container is never added as a target
filter, and neither the scoped address book nor send path changed.

CodeRabbit's security pass found that a mismatched `PALLIUM_MCP_TRANSPORT=stdio`
setting could bypass the wildcard MCP-bind check on the HTTP-mounted server.
The guard now requires a loopback MCP host regardless of that setting; the
MCP-to-ASGI regression asserts the mismatched setting is denied before lookup.
This conservatively denies the tool on the service's wildcard HTTP mount.

Independent result review found a count/page race under concurrent registration.
The Dashboard listing now begins an explicit SQLite read transaction before
both reads. Across separate tool calls, offset pages can still shift; guidance
says to treat them as observations rather than a frozen snapshot. No separate
authorization or semantic title-matching capability was added.

Skill feedback trigger 2 dropped: the corrected discovery guidance is owned by
Pallium, not the upstream Agent Workflow skill; this PR fixes that guidance.

## Evidence

`python scripts/test-plan.py --base origin/main` selected the full non-slow
lane because API/test files changed. After the transport guard fix, `uv run
--offline --extra dev --extra mcp --extra vector python -m pytest tests/ -x
-q` passed: 5,751 passed, 34 skipped, 2 xfailed (2026-09-30). The focused
transport-mismatch regression passed independently. The prior
focused MCP/HTTP/SQLite/guidance/tool-registration run passed 318 tests; the
last-failed rerun passed 38 tests with six deselected. The deterministic
concurrent-insert HTTP regression passed and the full rerun included it.
Import-linter produced no boundary violations. Redline classified the whole
path set as `SCHEMA_CHANGE`, with API and persistence review checkpoints in
shadow/advisory mode. `git diff --check` passed.
The initial Python 3.13 CI run failed in an unchanged Claude wake test; its
isolated GitHub job rerun passed, as did the Python 3.12 and Windows smoke jobs.
The amended PR commit requires fresh CI before merge.

## Result review

Agent technical review: `/root/global_lookup_result_review` (independent gpt-6-sol high).
Reviewed revision: tracked working diff `28b0b92a2b90f9b564724daadee419647a0e218c` against base
`0a42331514287f799ff852b67b369072b2682fe8`, plus inspected untracked
Work Record and roadmap item. The review found a count/page race, resolved by
an explicit read snapshot and deterministic concurrent-insert test, then
reported no remaining actionable code finding.
The same independent reviewer then inspected the transport-guard delta and
confirmed it closes CodeRabbit's inferred exposure without an actionable
finding; the reviewed delta was against `3577c10b135a17ae576cc457b03b56472bcf97b9`.
Verification adequacy: focused
caller E2E, representative query plan/index assertion, selected full suite,
and boundary check cover the approved criteria; skipped/xfail tests retain
their normal baseline status. Separate human High-risk result review and PR
API/persistence checkpoint satisfaction are pending.
