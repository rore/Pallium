# Historical lookup active-session linkage

Branch: `codex/historical-lookup-session-linkage`

<!-- agent-workflow:start -->
**Outcome:**
Historical lookup and expansion events issued through Pallium's local Codex and Claude integrations carry the active agent task/session identity used by captured turns, so downstream work can be joined to the lookup that preceded it.

**Target:**
Pallium repository.

**Scope:**
MCP active-context propagation for the existing Codex/Claude integrations, focused caller-surface tests, operations/measurement documentation, roadmap alignment, and this Work Record. No event schema, HTTP route, production retrieval/ranking, visibility, or authorization change.

**Constraints:**
Pallium has no authorization layer and this identity remains telemetry only. Never substitute the historical anchor/source session for the active requester. Preserve callers that provide no identity, existing container canonicalization, visibility behavior, launcher policy, and the Windows VBS service launcher.

**Completion criteria:**
When a Codex or Claude task ingests turns and then searches/expands history, the persisted lookup/expansion event shall carry the same active session ID as that task's source_items.thread_ref, enabling a positive eval-time join. Missing active identity remains explicit rather than fabricated. Caller-surface lifecycle tests, full regression, installed integration refresh, service restart/health, and a fresh read-only linkage verification pass.

**Risk:**
Elevated

**Complexity:**
Moderate

**Reason:**
Redline classifies shared MCP/runtime and integration installer paths GRAY, with no boundary, API, schema, persistence, security, or runtime-config-policy finding. Complexity is Moderate because a long-lived MCP process does not inherently know the invoking task identity and both integrations must preserve compatibility.

**Discovery:**
The HTTP/MCP persistence path is already correct when `thread_ref` is explicit: the focused funnel E2E passes, and both MCP tools accept an optional active `thread_ref`. Codex and Claude hooks already receive the exact host `session_id` and use it as captured turns' `thread_ref`, but their injected context exposes only `container_ref`; agents therefore cannot pass the matching session to deliberate history tools. Official Codex MCP configuration exposes static process environment, not a dynamic per-task ID. A server-global or latest-session fallback would corrupt concurrent attribution. Live pre-change evidence: 37 lookup events, only 2 with any session_id, and 0 matching captured source thread_ref.

**Material assumptions:**
- Confirmed: both host hooks supply a stable `session_id` for the task and already persist turns under it.
- The agent will follow the installed Pallium skill when it says to pass the injected `thread_ref`; verification must exercise the caller surface, not only the HTTP service.
- Identity remains optional telemetry. Missing or malformed host identity stays explicit; it is never guessed from another task or used as authorization.

**Plan:**
1. Extend each integration's existing injection formatter with an optional `thread_ref`. Emit one compact, control-character-safe scope marker when a valid identity is present, including when no memory block was retrieved; preserve Unicode and the existing hard `budget_chars` ceiling, returning no marker rather than truncating/fabricating an identity when it cannot fit.
2. Pass the host `session_id` from SessionStart and UserPromptSubmit. Remove the existing fabricated `"unknown"` fallback from both prompt and stop capture paths so missing identity stays `None`/unattributed. Do not add storage, registries, environment mutation, server state, authorization, or changes under `app/mcp`.
3. Update both installed-skill sources to require the injected active `thread_ref` on historical search and source expansion. Add focused Codex/Claude hook-surface and formatter tests for memory-present, memory-absent, missing identity, control characters, Unicode, tiny budgets, long IDs, and two distinct task identities. Extend the existing MCP E2E readback to assert active session B, source session A, lookup→expansion linkage, and cross-session access remains allowed because identity is telemetry only.
4. Reopen and narrow the existing roadmap item to the remaining real-install integration gap; remove stale auth-like/out-of-scope completion language. Align operations/measurement docs. Run focused and full regression checks, workflow/redline checks, then push, open and close the PR. After merge, reinstall both local integrations, preserve the VBS launcher, restart the service, and verify health plus a fresh attributed lookup.

**Verification plan:**
- Exact hook scope and budget boundaries → focused Codex and Claude hook/formatter tests.
- Active B versus source A plus parent linkage → existing MCP caller lifecycle E2E with persisted event readback.
- Missing identity, Unicode, controls, long IDs, and distinct tasks → focused integration boundary tests.
- Regression, workflow, install, and live operation → full pytest; agent-workflow/redline checks; post-merge integration refresh; VBS service restart; `/health` and live linkage readback.

**Plan review:**
Clean-context review initially withheld approval on missing-session semantics, formatter bounds/sanitization, caller-surface E2E specificity, roadmap drift, and unnecessary MCP-edit ambiguity. After revision, the same clean-context reviewer APPROVED with all five findings addressed and no remaining blockers.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established context from live aggregate evidence and the passing explicit-thread funnel E2E. Clean-context redline classified the intended MCP/integration scope GRAY, requiring Elevated review.
- The repository-local patch mechanism previously failed on this machine with Windows error 1385; this Work Record was created through the documented deterministic, single-file .NET fallback before code inspection.
- Implementation stayed in the approved Codex/Claude hook, shipped-guidance, test, roadmap, operations-doc, and Work Record surfaces. Protected `app/mcp`, core, storage, schema, route, auth, launcher, and service-config paths remain unchanged.
- The lower-cost implementer stalled, then produced a late malformed overlapping hook edit after interruption. The nine exact hook files were verified as task-owned, restored to branch HEAD, and the approved change was reapplied directly. All subsequent writes used the documented narrow deterministic fallback because `apply_patch` had already failed with Windows error 1385 in this task.

## Evidence

- Compile check passed for both hook trees and the three touched test files.
- Focused established-header plus integration/MCP suite: 57 passed; three pre-existing Pydantic warnings.
- Final full isolated regression after result-review fixes: 3,698 passed, 23 skipped, 2 expected failures, and four pre-existing Pydantic warnings. A first non-isolated run exposed the machine-local `pallium.local.toml` in one unrelated config test; that test and the full suite pass with `PALLIUM_CONFIG_FILE` pointed to a nonexistent isolated path.
- MCP lifecycle E2E proves cross-session access remains allowed while lookup and expansion persist active session B, source session A, and the lookup parent link.
- CodeRabbit final review found Unicode line and paragraph separators could still break scope-marker layout. Both shared formatters now reject Zl and Zp; the two focused regressions pass.
- Local operational proof (2026-08-23): Codex and Claude integrations were refreshed with strong guidance and installed skill hashes match their sources; the existing VBS-backed service restart returned OK; health reported status=ok, vector_index_ready=true, and embedding_provider_ok=true.
- Fresh live readback: lookup and expansion both persisted active task codex:live-verification:pr-54; expansion separately retained source task 019ffab9-b2b7-7492-b688-85e43a9f61b0 and parent lookup 241d79fb-3493-477d-897b-88e815888cc9.
- No file under `app/mcp`, core, storage, schema, route, auth, launcher, or service configuration changed.

## Plan review

Clean-context plan review approved after the plan made missing identity explicit, bounded and control-safe scope formatting, caller-surface E2E, roadmap drift repair, and no-MCP-edit scope mandatory.

## Result review

Independent result review found one P1 hard-budget overflow when memory blocks were present but none fit. Both mirrored fallbacks now recheck the scope-marker length, both integrations have the block-present tiny-budget regression, the focused suite passed, and the reviewer APPROVED with no remaining blocker.