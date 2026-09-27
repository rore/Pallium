# Inert Codex MCP Desktop bridge

Canonical feature: `roadmap/features/add-wake-first-relay-delivery.md`.
Owner: relay-dev. Bounded implementation continuation of the private Desktop bridge feasibility/design task; no experimental history is copied into this clean branch. Reviewed design checkpoint: `abca7f4f`; design-only acceptance does not approve production activation.

<!-- agent-workflow:start -->
**Outcome:** Integrate an inert, optional Desktop bridge lifecycle into the existing Codex-local stdio MCP without changing normal tools or issuing Desktop actions.

**Target:** Pallium Codex-local MCP integration; inert lifecycle only.

**Scope:** app/mcp/server.py, app/mcp/codex_desktop_bridge.py, tests/test_codex_mcp_desktop_bridge.py, docs/designs/codex-mcp-desktop-bridge.md, roadmap/features/add-wake-first-relay-delivery.md, and this Work Record.

**Constraints:** Off by default; eligible only through explicit Codex-local stdio entrypoint opt-in with inherited capability presence. No native connection or calls, HTTP service observation, payload/claim/ACK, grants, live setup/configuration, service/app restart, session settings, scope/TTL/retry changes, dependencies, or protected behavior-contract edits. Preserve private experimental history; do not publish it. Tests use deterministic fakes only. Busy-turn policy remains deferred.

**Completion criteria:** Disabled, HTTP/SSE, non-Codex, missing capability, and invalid opt-in create no bridge effects. Eligible inert stdio startup and bounded shutdown preserve concurrent normal MCP responses under contained import/startup/background/transport faults and EOF/cancellation. Caller-surface tests assert zero Desktop actions and no capability leakage/stdout pollution. Normal tools/schema remain unchanged. Required validation and independent review pass; roadmap distinguishes inert lifecycle from cold delivery.

**Requirement baseline:**
{"source":"Task-owner inert implementation continuation, 2026-09-27","outcome":"Integrate an inert, optional Desktop bridge lifecycle into the existing Codex-local stdio MCP without changing normal tools or issuing Desktop actions.","scope":"app/mcp/server.py, app/mcp/codex_desktop_bridge.py, tests/test_codex_mcp_desktop_bridge.py, docs/designs/codex-mcp-desktop-bridge.md, roadmap/features/add-wake-first-relay-delivery.md, and this Work Record.","constraints":"Off by default; eligible only through explicit Codex-local stdio entrypoint opt-in with inherited capability presence. No native connection or calls, HTTP service observation, payload/claim/ACK, grants, live setup/configuration, service/app restart, session settings, scope/TTL/retry changes, dependencies, or protected behavior-contract edits. Preserve private experimental history; do not publish it. Tests use deterministic fakes only. Busy-turn policy remains deferred.","completion_criteria":"Disabled, HTTP/SSE, non-Codex, missing capability, and invalid opt-in create no bridge effects. Eligible inert stdio startup and bounded shutdown preserve concurrent normal MCP responses under contained import/startup/background/transport faults and EOF/cancellation. Caller-surface tests assert zero Desktop actions and no capability leakage/stdout pollution. Normal tools/schema remain unchanged. Required validation and independent review pass; roadmap distinguishes inert lifecycle from cold delivery."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** RED app/mcp/server.py requires api-review attention; tools/signatures stay unchanged but shared MCP lifecycle is load-bearing. New app module is GRAY/watch; docs/tests are BLUE. No persistence/security contract or forbidden import is changed.

**Discovery:** Existing create_server is shared by local stdio and HTTP service construction; startup mode must be explicitly selected at the entrypoint rather than inferred in registration. Installed FastMCP exposes public lifespan callback; run_stdio_async enters the low-level server lifespan. Existing Codex identity is per-request metadata, not a process-wide task ID. No authenticated bridge channel exists; capability presence is availability only.

**Material assumptions:** Optional contained faults can be isolated in-process, not process crashes or memory exhaustion. If supported lifespan teardown cannot bound cooperative async tasks, narrow/pivot before implementation rather than promise hard isolation. No live capability connection is needed for the inert slice. Future grant origin-binding, busy-safe admission, and executor availability/bootstrap remain activation gates.

**Plan:** Invoke Agent Workflow first and classify the exact paths before code. Obtain independent plan clearance. Use a clean managed branch from origin/main and a sanitized bounded Work Record, preserving the private umbrella record/baseline. Reuse FastMCP's public lifespan with explicit Codex-local stdio eligibility. Lazy-import the optional app module only after eligibility; contain import/startup/background failures and bounded cancellation without suppressing normal server exceptions. The inert module performs no network/native I/O; resources are deterministic test fakes. Preserve normal tool registration/schema and protocol-only stdout. Implement focused caller-surface tests before broader validation. Stop/replan on new live I/O, setup, mutation, authority, or unbounded shutdown requirement.

**Verification plan:**
When eligibility is absent or HTTP/non-Codex construction occurs, no optional import/task or Desktop action occurs -> MCP entrypoint/stdio/HTTP caller-surface tests.
When inert startup or its cooperative task/transport fails, concurrent normal tool calls still complete and stdout stays protocol-only -> deterministic stdio client E2E fault matrix.
When EOF/cancellation/shutdown occurs, owned resources stop within a finite bound with no native action -> caller-surface lifecycle E2E and contained teardown cases.
When multiple children run, each remains inert with unchanged schemas and no authority or capability disclosure -> concurrency/schema/output assertions.
When implementation is coherent, protected existing delivery/retry behavior remains unchanged -> affected MCP subsystem and scripts/test-plan.py selected checks, full non-slow suite once, import-linter and workflow.

**Plan review:** Agent technical review: mcp_bridge_arch_review, independent manager-conveyed clearance of exact inert plan and sanitized linked Work Record on 2026-09-27, before code. One cancellable idle task with fixed local state; no transport/client/runner framework. Contain ordinary startup/background faults without suppressing normal MCP exceptions; preserve cancellation/finite cleanup. Guard before optional import, preserve lifecycle-free HTTP, catalog/schema, concurrent normal response, bounded EOF/cancellation, and zero native/service bridge activity. RED api-review attention retained.

**Approvals:** Task owner authorized driving implementation and qualification through required gates on 2026-09-27. No changed busy-turn contract or production wake activation is approved. Not High risk; human plan approval format not required.

**Exceptions:** None

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

New isolated branch starts at `62a4cf5edf7b5cb873595888d0f46cf5d8ec24ff`. Independent plan clearance received before code. Bounded Luna worker owns app/mcp/server.py, app/mcp/codex_desktop_bridge.py and tests/test_codex_mcp_desktop_bridge.py only; root owns record/design/roadmap and reviews its output. This continuation does not clear the private spike's publication restriction or claim automatic unloaded delivery. Future lifecycle qualification is separate, using authorized disposable contexts without restarting Desktop or unloading working sessions.

## Evidence

Supported lifespan inspected in the existing MCP dependency; no tests or live experiments run in this planning checkpoint.

## Result review

Pending implementation and required verification.
