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

**Risk:** High

**Complexity:** Moderate

**Reason:** RED app/mcp/server.py triggers api-review, a contract-class High floor in the workflow checker even with unchanged tool schemas. The earlier Elevated classification was incorrect and is corrected at final verification. New app module is GRAY/watch; docs/tests are BLUE. No persistence/security contract or forbidden import is changed.

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

**Approvals:** Approved by user 2026-09-27: "ok, so drive this topic. manage this and the quality of the work. only stop if there's a blocker or a change of assumption that is critical, you can't solve and needs my attention". Task-owner authorization was conveyed by the expert manager following the six-stage plan with this inert slice first; exact private source provenance is retained in the linked umbrella record. This is plan/implementation authorization, not separate human result review. No changed busy-turn contract or production wake activation is approved.

**Exceptions:** None

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Implementation checkpoint: Luna implemented the entrypoint/public lifespan and one idle task; root/manager review added fixed cooperative entry/exit deadlines and diagnostic-sink containment before acceptance. Non-empty capability presence is checked transiently with bool(env lookup), never retained/copied/logged; it is not connectivity or authority. Worker first focused run found six fake-client constructor failures (14 passed/6 failed), not native behavior. Root took over that bounded test fix: ctx constructor, semantic exact JSON success assertions, full Tool catalog/schema equality, real stdio post-main EOF marker, fake normal clients/URL, cooperative outer cancellation, and lifecycle-free actual ASGI JSON HTTP negative. Removed redundant weak memory fault matrix; no accepted behavior was weakened. SDK SSE watcher leaked from an in-process test, so the HTTP negative uses supported JSON representation rather than suppressing or changing production SSE behavior. No live setup or runtime mutations.

New isolated branch starts at `62a4cf5edf7b5cb873595888d0f46cf5d8ec24ff`. Independent plan clearance received before code. Bounded Luna worker owns app/mcp/server.py, app/mcp/codex_desktop_bridge.py and tests/test_codex_mcp_desktop_bridge.py only; root owns record/design/roadmap and reviews its output. This continuation does not clear the private spike's publication restriction or claim automatic unloaded delivery. Future lifecycle qualification is separate, using authorized disposable contexts without restarting Desktop or unloading working sessions.

## Evidence

Historical pre-validation: complete six-path union classified RED (server.py api-review), GRAY/watch (new app module), BLUE (docs/tests), with no boundary violations from the existing import-linter backend. Whole-change selector required the full non-slow lane. Root/manager early review requested cooperative startup/teardown timeouts, diagnostic-sink containment, actual subprocess stdio evidence, exact successful normal responses, and full schema/catalog equivalence; these corrections were completed before the passing verification below. No checkpoint label is claimed.

Skill feedback Trigger 2 dropped: evidence/provenance/marker corrections concern this task's drafting and test adequacy, not a repeatable upstream skill defect; no public report is appropriate.

Historical planning checkpoint: supported lifespan was inspected in the existing MCP dependency before code; no tests or live experiments had run at that point.

Implementation verification: affected MCP files passed (285 passed, 87.79s); `scripts/test-plan.py --base origin/main` selected the full lane; `python -m pytest tests/ -x -q` passed (5364 passed, 34 skipped, 2 xfailed, 333.33s). SHA256: `app/mcp/server.py` F6A2B0D7891B4ECE1639FB758C9D85185A5DC9FEB74EDC4CB2CF01552F7D9805; `app/mcp/codex_desktop_bridge.py` 0EF475325DB58455028BC3CDC619810936D64CF0005F44EDE6009D98E1668D57; `tests/test_codex_mcp_desktop_bridge.py` 9E977614C552BE07B3D2F4318B785C50425FAE636420FE858016FD13D7EEA313.

## Result review

Agent technical review: independent clean-context `mcp_bridge_arch_review`, conveyed by expert manager on 2026-09-27; final source and test-only corrections accepted contingent on the now-passing affected/full checks. Root inspected the complete implementation and final test corrections. No additional unchanged-source rerun or review loop is needed.

Reviewed revision: working delta from planning checkpoint `44bdb2d0`, bound to the three exact SHA256 hashes in Evidence above. Production hashes are unchanged from independent review; the final test-only corrections were separately accepted.

Verification adequacy: sufficient for the inert slice: actual stdio failure/concurrency/EOF paths, full tool schemas, successful normal responses, cancellation, and lifecycle-free HTTP negative passed along with the affected MCP and full non-slow suites. Containment is cooperative in-process, not process-crash isolation. No Desktop/service bridge action, live setup, installation or automatic cold wake is claimed. RED api-review attention remains a PR checkpoint; no label is asserted. Canonical roadmap now separates validated inert work from still-unqualified activation and host lifecycle.

Final gate: fresh workflow check detected the contract-class High floor from api-review. Root corrected its prior risk misclassification; no policy, source, baseline or review evidence was weakened. Independent review conditions are discharged by passing checks, confirmed by manager. Separate human result review remains pending before merge/release. Manager verified that this result gate does not prohibit already-authorized pre-review validation. Live qualification belongs only to the separate private umbrella phase, not this inert implementation's immutable baseline. No live setup is part of this diff. Skill-feedback Trigger 2 dropped: this is root's risk-mapping error, not an upstream instruction defect.
