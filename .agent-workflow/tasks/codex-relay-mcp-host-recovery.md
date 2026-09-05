<!-- agent-workflow:start -->
**Outcome:** Codex Relay MCP recovery uses exact per-call runtime metadata, ignores stale inherited task IDs, and fails closed without claiming when the client does not provide one unambiguous task identity.

**Target:** Pallium Codex setup and Relay MCP runtime-identity boundary.

**Scope:** `app/mcp/context.py`, `app/mcp/server.py`, `app/cli/setup_codex.py` only if discovery disproves the shipped env allowlist, focused MCP/setup caller-surface tests, `docs/codex-integration.md`, and Relay roadmap/Work Record state. Do not touch Codex hooks unless the separate vnext workstream confirms sequencing and a test proves they are required.

**Constraints:** Preserve runtime-owned identity and fail closed; never accept model/tool arguments, inherited process variables, or parent-process scraping as Codex session identity, and never mix hook delivery with MCP receive in one session. Keep deterministic tests fast and avoid host restarts in the normal suite. No hook edit is planned; coordinate through Relay if that changes.

**Completion criteria:** (1) A real MCP call whose transport metadata contains one exact Codex task ID can claim and ACK only that task's pending delivery, even when the child inherits a different outer `CODEX_THREAD_ID`/`CODEX_SESSION_ID`. (2) Top-level `threadId` and nested `x-codex-turn-metadata.thread_id`/`session_id`, when present, must be printable non-blank strings of at most 255 characters and must all agree; absent, malformed, or conflicting metadata claims nothing. Unknown metadata keys are ignored. (3) No tool argument can supply or override session identity. (4) Existing non-Codex context, hook delivery, scope isolation, receive/ACK, and relaunch behavior remain unchanged. (5) The roadmap marks RW-006 complete only after deterministic real-stdio coverage and an isolated installed witness.

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Pre-edit redline verdict is GRAY because `app/**` runtime paths are watch surfaces; tests/docs are blue and no boundary or checkpoint applies. Moderate complexity covers process-lifecycle qualification, fail-closed messaging, and an isolated live witness across stale/fresh children.

**Discovery:** Commit `50b8ad89` shipped an `env_vars` allowlist, but official Codex config documentation defines it as forwarding local environment variables, not injecting current task identity. Installed witness proved a fresh nested task inherited the outer ID. A raw Codex 0.149.1 MCP probe then proved that the actual `tools/call` RequestContext metadata supplies exact top-level `threadId` and matching nested turn metadata. The root fix belongs at the per-request MCP boundary; no hook or process registry is needed.

**Material assumptions:** (1) Disproved 2026-09-05: Codex `env_vars` forwards the launcher's environment; a nested fresh task inherited the outer task's `CODEX_THREAD_ID` and its MCP receive bound to the wrong session. (2) Proven by an isolated Codex 0.149.1 MCP probe: every tool call carries exact runtime-owned `threadId` plus matching `x-codex-turn-metadata.thread_id`/`session_id`. Treat matching request metadata as authoritative only for the Codex runtime; absent, malformed, or conflicting values must fail closed before Relay HTTP. (3) The installed MCP SDK can reproduce these request metadata shapes against the real `python -m app.run mcp` stdio child without a model or network; inability returns the task to planning. (4) Older Codex clients may omit this metadata; safe compatibility is an actionable upgrade/reload error, never inherited or model-supplied identity.

**Plan:** 1. Remove Codex session identity from the MCP launch-environment allowlist and resolver; inherited `CODEX_THREAD_ID`/`CODEX_SESSION_ID` are not authoritative. 2. Inject FastMCP `Context` into `pallium_relay_receive` and add one small RequestContext metadata resolver at that boundary. Accept only top-level `threadId` and nested `x-codex-turn-metadata.thread_id`/`session_id`; each supplied value must be a printable, trimmed, non-blank string of at most 255 characters and all values must agree. Ignore unknown keys. Missing, malformed, or conflicting metadata fails closed before HTTP. Other runtimes retain their existing integration-owned context. 3. Replace the three-process test with one fast real stdio child carrying deliberately wrong inherited outer IDs while SDK `ClientSession.call_tool(..., meta=...)` supplies multiple per-call Codex task IDs; receive and ACK only exact deliveries and cover direct/nested agreement, missing metadata, conflicts, malformed/control/over-max values, unknown keys, no session tool argument, and zero HTTP on refusal. 4. Run focused setup/context/MCP/hook-isolation suites plus workflow/redline/diff checks. 5. Reinstall the Codex integration and run one synthetic empty-scope installed-profile witness proving the MCP response reports the newly created task ID while wrong outer inherited IDs are ignored. No hook edit is required.

**Verification plan:** When a real stdio `tools/call` carries exact Codex RequestContext metadata, Relay shall claim and ACK only that task's delivery regardless of wrong inherited outer IDs -> SDK caller-surface lifecycle test. When accepted metadata locations disagree, contain invalid types/control characters, exceed 255 characters, or are absent, Relay shall make zero HTTP/claim calls -> transport-boundary regressions. The tool schema shall expose no session identity argument -> schema assertion. Existing non-Codex scope conflicts and hook/MCP isolation shall remain fail-closed -> affected suites. An installed synthetic-scope witness shall assert the response task ID equals the new Codex task and differs from inherited outer IDs.

**Plan review:** Approved clean-context re-review (`/root/mcp_plan_review`): prior real-stdio caller-surface blocker resolved.

Revised metadata plan approved by clean-context review (`/root/rw006_replan_review`) after rejecting the PID-registry design and resolving all acceptance, transport-schema, trust-boundary, compatibility, and installed-witness blockers.

**Approvals:** Not required at this risk level; the user explicitly requested closing all open bugs and has standing approval for managed PRs.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- 2026-09-05: Established scope, completed discovery, and classified the intended diff GRAY/Elevated with no boundary or checkpoint. No production code edited.
- 2026-09-05: Superseded attempt: added environment-based stdio qualification, then rejected it when the installed witness proved a fresh nested task inherited the outer task ID.
- 2026-09-05: Installed live witness disproved the environment-handoff assumption: fresh nested Codex task `01a07278-6f4f-7262-8a9a-ada34b43d048` called the installed MCP tool successfully, but the Relay session response reported outer task `01a061a3-4745-7943-ae34-c322967cae36`. Returned to planning before accepting the slice.
- 2026-09-05: A uniquely named local MCP metadata probe on Codex 0.149.1 returned exact fresh task `01a07280-79bf-7503-87ff-f27b7542b53a` in both top-level `threadId` and nested turn metadata. Replaced the rejected PID-registry plan with per-request runtime metadata.
- 2026-09-05: Implemented per-request metadata authority, removed inherited Codex identity and setup allowlisting, added fail-closed validation, and collapsed the lifecycle regression to one real stdio child.
- 2026-09-05: Clean-context code review found one optional-dependency regression; moved FastMCP Context loading back inside create_server() and added an import-without-MCP subprocess regression. Re-review found no blockers.

## Evidence

- Pre-edit redline review `/root/mcp_redline`: GRAY `app/**` watch paths, blue tests/docs/Work Record, no boundary risk or required checkpoint.
- Discovery correction: installed witness disproved the shipped environment allowlist as identity authority; raw MCP RequestContext metadata is the exact per-call task identity.
- Final deterministic gate: one real `python -m app.run mcp` stdio child carried three wrong inherited IDs while per-call SDK metadata selected exact ASCII, Unicode, and 255-character task IDs; exact receive+ACK succeeded, tool schema exposed no session argument, and absent/conflicting/malformed/control/over-max metadata made zero HTTP calls. Broader focused command covering MCP, Codex integration/wake, Relay contract/E2E/lifecycle: 160 passed in 16.34s with four pre-existing Pydantic warnings.
- Clean-context implementation review (/root/rw006_replan_review): initial optional-MCP import blocker fixed; re-review found no blockers. Focused post-fix MCP suite: 49 passed in 7.88s with four pre-existing Pydantic warnings.
- Installed synthetic empty-scope witness after reinstall: new Codex task and returned Relay session both `01a07296-aa6c-73f2-8f07-6ffa441a845f`, distinct from outer task `01a061a3-4745-7943-ae34-c322967cae36`; no hook delivery or private payload was involved.

## Plan review

Initial verdict: Blocked pending one plan correction.

The identity boundary and scope are consistent with the existing code: context.py already prefers integration-owned PALLIUM_THREAD_REF and Codex-owned CODEX_THREAD_ID/CODEX_SESSION_ID, server.py fails closed before calling Relay, and setup_codex.py already emits the two-variable allowlist. The proposed actionable Codex-only error is appropriately scoped and must not weaken the generic fail-closed behavior for other runtimes.

Material blocker: the completion criteria require a newly launched MCP child to claim and ACK through the real MCP tool surface, but Plan step 3 says to use subprocess/stdio “only if the existing harness supports it cleanly.” That conditional permits a direct in-process FastMCP test to pass while the actual Codex-launched stdio child still drops the runtime environment. Revise the plan and verification to require a deterministic subprocess/stdio caller-surface test for both allowlisted variables, stale-child failure/restart guidance, exact-session isolation, receive/ACK, and relaunch recovery. A harness limitation should return the task to planning, not downgrade the gate; the isolated installed-host witness remains a separate check. No production, test, hook, or documentation change was made during this review.

Correction applied; re-review completed.

Re-review verdict: Approved. The material blocker is resolved: the material assumptions now require the installed SDK to drive the real python -m app.run mcp stdio child, and the plan explicitly requires a mandatory subprocess/stdio lifecycle test covering stale identity, both Codex variables, isolation, receive/ACK, and relaunch recovery. Harness inability returns the task to planning, so no weaker in-process substitute can satisfy the gate. The plan is ready for implementation within the recorded scope; no production, test, hook, or documentation change was made during review.
