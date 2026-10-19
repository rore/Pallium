# Hermes slice 2: installable skill and trusted MCP package

Canonical item: `roadmap/features/add-hermes-agent-integration.md`
(`add-hermes-agent-integration`). Branch `feat/hermes-package-slice2`.
Owner checkout: `C:\Users\I347041\.codex\worktrees\hermes-package-slice2\Pallium`.
Stack base: pushed slice-1 checkpoint `377327dd39d3660284224f0e8cfcae7c2b4ac725`.
Main merge base: `701608cd0f666fe5106bf7c91e2e98bf0fe21d0c`.
Slice 1 remains separately pending compatible-environment full validation; do not
silently import an unmerged reliability candidate or repeat source-only probes.

<!-- agent-workflow:start -->
**Outcome:**
Provide an installable Hermes Pallium package with bundled skill/guidance and trusted per-conversation MCP tools, proving Hermes-originated recipient discovery and send, a peer reply, automatic Hermes wake and receipt, safe repeated setup, status and clean removal.

**Target:**
Hermes v0.22.2 integration in an isolated Windows gateway/profile with a local provider stub and a disposable Pallium service/data store.

**Scope:**
A new slice-2 Work Record; integrations/hermes plugin, manifest, README, bundled skills and references; app/cli/setup_hermes.py and app/run.py setup dispatch; app/mcp/hermes.py, app/mcp/context.py and app/mcp/server.py only as needed for a supported host-bound MCP identity adapter reusing shared tools; tests/test_setup_hermes.py, tests/test_hermes_mcp.py, tests/test_hermes_relay_plugin.py and tests/test_hermes_relay_native_e2e.py; roadmap/features/add-hermes-agent-integration.md and its directly affected roadmap/scope.md paragraph. Disposable TEMP environments, pinned source, profiles, loopback endpoints and test data only.

**Constraints:**
Preserve reliability-owned checkouts, scheduler/retry/claim/ACK/storage authority, existing runtime contracts, protected behavior tests, CI, dependencies and governance. No live installation/configuration, global packages/PATH/environment, user app/service operations, paid inference or installed port 19836. Model arguments and profile-wide static identity cannot select the current conversation. Use public supported Hermes and MCP surfaces; no host patches/private registries, process-global identity mutation or competing queues. Keep broader History capture and optional-memory qualification in their planned later slices. Push recoverable branch checkpoints; coordinate full-suite resource slots.

**Completion criteria:**
Disposable-profile E2E drives supported package setup, verifies skill/MCP discovery, makes actual Hermes tools discover and send to a peer, receives the peer reply by automatic wake in the same Hermes conversation, repeats setup without damage, and removes only package-owned artifacts. Caller-surface tests cover missing/conflicting identity, concurrent sessions, invalid scope/arguments, permission/service errors, bounds/Unicode, rollback and changed-user-configuration preservation. Required checks and independent review are recorded; unfinished qualification remains explicit.

**Requirement baseline:**
{"source":"user:c0a7fde2-6072-4f47-b8a4-9871a0a19dab","outcome":"Provide an installable Hermes Pallium package with bundled skill/guidance and trusted per-conversation MCP tools, proving Hermes-originated recipient discovery and send, a peer reply, automatic Hermes wake and receipt, safe repeated setup, status and clean removal.","scope":"A new slice-2 Work Record; integrations/hermes plugin, manifest, README, bundled skills and references; app/cli/setup_hermes.py and app/run.py setup dispatch; app/mcp/hermes.py, app/mcp/context.py and app/mcp/server.py only as needed for a supported host-bound MCP identity adapter reusing shared tools; tests/test_setup_hermes.py, tests/test_hermes_mcp.py, tests/test_hermes_relay_plugin.py and tests/test_hermes_relay_native_e2e.py; roadmap/features/add-hermes-agent-integration.md and its directly affected roadmap/scope.md paragraph. Disposable TEMP environments, pinned source, profiles, loopback endpoints and test data only.","constraints":"Preserve reliability-owned checkouts, scheduler/retry/claim/ACK/storage authority, existing runtime contracts, protected behavior tests, CI, dependencies and governance. No live installation/configuration, global packages/PATH/environment, user app/service operations, paid inference or installed port 19836. Model arguments and profile-wide static identity cannot select the current conversation. Use public supported Hermes and MCP surfaces; no host patches/private registries, process-global identity mutation or competing queues. Keep broader History capture and optional-memory qualification in their planned later slices. Push recoverable branch checkpoints; coordinate full-suite resource slots.","completion_criteria":"Disposable-profile E2E drives supported package setup, verifies skill/MCP discovery, makes actual Hermes tools discover and send to a peer, receives the peer reply by automatic wake in the same Hermes conversation, repeats setup without damage, and removes only package-owned artifacts. Caller-surface tests cover missing/conflicting identity, concurrent sessions, invalid scope/arguments, permission/service errors, bounds/Unicode, rollback and changed-user-configuration preservation. Required checks and independent review are recorded; unfinished qualification remains explicit."}

**Risk:** High

**Complexity:** Moderate

**Reason:**
Host-bound MCP identity and package setup cross trust/configuration boundaries. app/mcp/server.py is a red API checkpoint; the whole stacked branch also retains reviewed core/API red-zone changes from slice 1. No persistence or dependency change is authorized.

**Discovery:**
Slice 1 proves a native reply-only tool using public tool_execution middleware session/turn context, normal authorization and a ContextVar. Existing Pallium MCP context supports Codex request metadata and Claude runtime identity, but not Hermes. Hermes MCP connections are profile-shared, so static MCP environment cannot identify concurrent conversations. Existing setup_codex/setup_claude_code and bundled pallium-memory references provide package conventions. Two cheaper workers are inspecting public MCP identity and packaging/harness surfaces read-only; no slice-2 application edit has begun.

**Material assumptions:**
A public Hermes tool/MCP boundary can carry trusted actual session/turn scope into the existing Pallium tool surface without model identity or host patching. If unsupported, record the exact blocker and reassess before code rather than relabel a native-only wrapper as MCP. Supported config/skill/plugin paths permit a merge-safe disposable-profile installer; if not, report the missing extension point. Qualification remains the explicit pinned/local-stub topology until broader evidence exists.

**Plan:**
1. Invoke Agent Workflow, evaluate whole-change applicability, create this record and classify risk before application edits.
2. Inspect pinned public Hermes MCP/tool/config/skill APIs and existing Pallium tool/setup contracts; choose the smallest supported identity and package path. Obtain clean-context technical plan review before implementation.
3. Implement trusted per-call identity propagation for actual MCP dispatch, reusing common Pallium tools and preserving normal Hermes authorization. Missing/conflicting scope refuses; concurrent conversations cannot overwrite identity.
4. Bundle the Pallium skill/references/guidance and add explicit profile-targeted setup/status/removal using existing CLI conventions. Preserve unrelated config, credentials/data, backups and changed-user artifacts; repeated setup is idempotent. Never run this against the user's live profile.
5. Extend the real-host/provider-stub E2E from package install through discovery/send, peer reply, idle wake/receipt, repeat setup and removal. Add caller-surface identity/configuration/error/lifecycle controls.
6. Run focused tests, whole-change selector and required workflow/boundary checks. Run the full non-slow suite only in an allocated resource window with compatible isolated dependencies. Obtain independent result review, reconcile the canonical item, push checkpoints and leave human review/remaining qualification explicit.
Key conventions: existing app/cli setup dispatch and shared MCP tool/client contracts; integration-specific identity stays in its adapter; metadata/receipt confidentiality and exact host identity are preserved. Target files are enumerated in Scope. No dependencies, shared reliability semantics or host support expansion without reassessment.

**Verification plan:**
When installed in a disposable Hermes profile, the package exposes its skill/guidance and actual MCP tools -> setup CLI and released-host inventory/tool-schema E2E.
When Hermes initiates a message, the exact sender conversation receives the peer reply through automatic wake -> real-host/local-provider-stub journey through ordinary Relay HTTP/MCP reads.
When identity/scope is absent, conflicting, stale or concurrent, no call impersonates another conversation -> actual MCP and native tool-middleware refusal/concurrency tests.
When setup is repeated, fails partway or removal follows user edits, only owned artifacts change and unrelated config/data survive -> CLI lifecycle/rollback E2E with normal status/read paths.
When permissions/service/arguments/bounds fail, errors remain bounded and no false send/ACK occurs -> caller-surface negative tests including empty/max/over-max and Unicode.
When publishing the stacked change, existing contracts and imports remain valid -> test-plan selector, allocated compatible-environment full non-slow suite, workflow/import/Redline checks and independent review; protected behavior paths unchanged.

**Plan review:**
Pending clean-context technical review after the supported MCP identity seam is established. No slice-2 application implementation before acceptance.

**Approvals:**
Approved by user 2026-10-19: "ok, let's start slice 2. keep it isolated from the reliability work, use cheaper models where it makes sense, and push the work so we don't lose it."
This approves the immediately preceding installable-package slice and disposable-profile acceptance journey, not live environment changes or broader History/memory implementation.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

- Created an isolated managed worktree from the pushed slice-1 branch; the shared
  development checkout's unrelated dirty files are preserved.
- Pre-edit whole-change applicability is normal workflow: app/MCP/plugin/setup
  paths are outside the documentation allowlist. No documentation-only exemption.
- Read-only discovery assigned to the existing cheaper Hermes workers with
  disjoint identity and packaging/harness scopes. Parent owns this record and roadmap.
- Coordination sent to authorized @astra-reviewer via Pallium Relay as
  `relay-msg-74d59ba3f5aa4cbd9796b7be11029fe7`; saved/pending is not acceptance
  or a test-slot allocation.

## Evidence

No slice-2 tests or application implementation yet. Slice-1 native/focused evidence
is retained in its own Work Record; no claim of slice-2 completion or broad support.

## Result review

Pending implementation and verification.

## Recovery

Owner: this chat. Next: finish public identity/package discovery and clean-context
plan review, then implement only the approved slice. State is Blocked on technical
plan review, with independent read-only discovery continuing. Keep this worktree
for the concrete slice-2 implementation; do not install it into everyday use.

