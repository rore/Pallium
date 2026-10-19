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
Slice 1 proves a native reply-only tool using public tool_execution middleware session/turn context, normal authorization and a ContextVar. Hermes native MCP and ctx.call_mcp omit per-call metadata; configured headers are connection-scoped. A plugin-owned standard MCP ClientSession is therefore required. Actual pinned MCP 2.0.0 in the disposable Hermes venv exposes call_tool(meta=...) and public stdio; the Pallium server uses MCP 1.29.1, so real interop must be tested. Existing shared send/name tools take explicit sender/current identities, requiring server-side checks beyond proxy-schema hiding. The dedicated entry reuses shared tool registrations through a default-inert optional registration adapter and a context-local trusted scope; public tool APIs only. Hermes supports a profile skill tree and public comment-preserving config writers. Existing setup modules supply ownership/staging conventions, but blind directory deletion is unsuitable. Cheaper discovery workers supplied exact source references; no slice-2 application edit has begun.

**Material assumptions:**
A public Hermes tool/MCP boundary can carry trusted actual session/turn scope into the existing Pallium tool surface without model identity or host patching. If unsupported, record the exact blocker and reassess before code rather than relabel a native-only wrapper as MCP. Supported config/skill/plugin paths permit a merge-safe disposable-profile installer; if not, report the missing extension point. Qualification remains the explicit pinned/local-stub topology until broader evidence exists.
Setup/removal requires exclusive offline access to that profile; Hermes' public config writer cannot guarantee atomic conflict handling with overlapping external writers. Detected preflight conflicts and preexisting user edits are preserved; overlapping writes and production setup remain unqualified.

**Plan:**
1. Invoke Agent Workflow, evaluate whole-change applicability, create this record and classify risk before application edits.
2. Inspect pinned public Hermes MCP/tool/config/skill APIs and existing Pallium tool/setup contracts; choose the smallest supported identity and package path. Obtain clean-context technical plan review before implementation.
3. Use a plugin-owned standard stdio ClientSession to app.mcp.hermes. Discover actual tool schemas and register public Hermes tool proxies. Middleware binds the trusted session/turn around normal next_call; explicitly carry that immutable pair across the MCP thread/loop in request meta, never model arguments. Exact tool allowlist: pallium_relay_address, pallium_relay_recipients, pallium_relay_discover_recipients, pallium_relay_name, pallium_relay_work_refs, pallium_relay_attach_work_ref, pallium_relay_detach_work_ref, pallium_relay_participants, pallium_relay_send, pallium_relay_reply, pallium_relay_status, pallium_relay_trace. The dedicated server also registers only that list. Hide self identity/scope/private receipts in proxy schemas and inject authoritative values in handlers; server-side guard rejects absent/malformed/conflicting metadata and identity-bearing arguments, binds exact configured scope per request and preserves normal default-server behavior. Exclude receive/ACK because hooks own claim/ACK. Reply requires the exact admitted host session/turn/delivery, adds the private receipt only inside the handler, and retires the local fence only after accepted reply; retain the native reply-only fallback when MCP is not configured. No copied Relay HTTP implementation or private registry.
4. Bundle the Pallium skill/references/guidance and add explicit --home and --hermes-python profile-targeted setup/status/removal using existing CLI conventions. Check the optional MCP SDK and frozen local-provider/toolset/permission prerequisites before mutation; refuse incompatible settings rather than changing models, Tool Search or other integrations. Configure the plugin-owned bridge, not an unbound native MCP connection. Stage plugin and discoverable profile skill trees with ownership/fingerprint checks, preserve unrelated config/comments/credentials/data, use public Hermes config writer in the target interpreter, retain backups/rollback and changed-user artifacts; repeated setup is idempotent. Never run this against the user's live profile.
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
Agent technical review: /root/hermes_e2e_review, 2026-10-19, record checkpoint 31e11b15, accepted with the exact allowlist and server-side identity-enforcement conditions now incorporated in steps 3-4. Reviewer inspected pinned public middleware/MCP paths and shared server send/name/current-identity behavior, confirmed SDK 2.0 per-call metadata from primary source and requires actual stdio interoperability. Parent independently verified the actual disposable 2.0.0 signature. No host patch, private registry, model identity or profile-global current session. Direct stdio missing/conflicting identity and actual same-profile concurrency controls are required. Default factory registration must remain unchanged. Conditional acceptance is discharged by these concrete planning constraints; their behavioral evidence remains required before result acceptance.

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
- Fresh pre-edit Redline report confirms architecture/API shadow checkpoints,
  no boundary violations, High risk; whole-change union has 21 intended/changed
  paths. Artifacts are in `%TEMP%\pallium-hermes-package-slice2-01a1489e`.
- Read-only discovery assigned to the existing cheaper Hermes workers with
  disjoint identity and packaging/harness scopes. Parent owns this record and roadmap.
- Coordination sent to authorized @astra-reviewer via Pallium Relay as
  `relay-msg-74d59ba3f5aa4cbd9796b7be11029fe7`; saved/pending is not acceptance
  or a test-slot allocation.
- Implemented the dedicated stdio catalog and request-local server guard, optional
  plugin-owned MCP client/proxies, exact frozen profile binding and host-held reply
  receipts. Default registration remains on the same shared MCP tool functions.
- Implemented explicit-profile setup/status/removal and bundled skill/references.
  Parent review corrected failed-preflight rollback to preserve detected config
  edits and whole-owned-entry checks to preserve user-added fields. Target filters
  remain legitimate tool arguments; self identity stays host-bound.
- Independent review identified that Hermes' native writer has no atomic CAS or
  interprocess lock. Setup/removal qualification therefore requires exclusive
  offline access to the frozen disposable profile, as in the approved journey.
  The digest detects preflight conflicts; overlapping external writes and live
  production setup remain unqualified. Review accepted this explicit boundary;
  no OS-lock machinery or host patch was added. Existing edited artifacts and
  detected changes are preserved; uncertain writes never restore stale config.
- The actual MCP 2.0 client to Pallium 1.29 stdio catalog probe passed with 12
  tools and hidden model identity/receipt fields; the owned connection closed.
  SDK 2 uses public snake-case result fields, which the client now follows.
- Real-host package lifecycle/concurrent-conversation E2E passed through the
  production installer and actual pinned host. No full non-slow run or live setup
  has started locally. Draft PR #321 now owns the hosted full-suite evidence;
  the local slot request is on hold to avoid duplicating that run. Human result
  review remains required after technical validation.

## Evidence

Initial focused evidence (implementation checkpoint, native package journey still
pending): plugin contracts **49 passed in 24.73s**; direct stdio MCP to the real
Relay fixture **15 passed**; unchanged Relay MCP regression **165 passed**;
setup lifecycle **10 passed, 1 skipped** (Windows symlink permission unavailable).
The direct stdio test verifies real sender identity, send/reply state and original
sender inbox through normal Relay reads. Parent reviewed these worker results;
the earlier shape-only HTTP stub was replaced with the actual service fixture.
Slice-1 native/focused evidence remains in its own Work Record; no claim of
slice-2 completion or broad support. Full validation and human result review remain
open. No protected behavior contract, dependency or reliability code changed.
After independent review corrections, setup lifecycle/refusal coverage is now
**14 passed, 1 skipped in 1.28s**, including service-origin validation, filesystem
scope refusal and common GitHub scope canonicalization before staging.
Pinned optional MCP 2.0.0 and 11 supporting packages were installed only into the
existing disposable Hermes qualification venv; actual call_tool(meta=...) and
stdio signatures were inspected. Shared/global packages were unchanged.

Native package journey: **1 passed in 71.22s** against application checkpoint
`c250aec2df49c920ba23f1466ba60e824c4dac4d` and the accompanying native test diff.
The real host loaded the installed skill via `skill_view`, offered the exact 12
MCP tool schemas, and ran two conversations with distinct trusted identities and
overlapping discovery requests (two arrivals, peak two, no barrier error).
Both initiated sends through MCP, received the peer reply by automatic idle wake,
forwarded full attributed Unicode context to the local provider, ACKed after its
completion, and replied through MCP. Normal Relay reads verified delivered state
and peer receipt. Actual inbound receipts/tokens were absent from provider traffic.
Wrong-recipient and closed-session controls never claimed/ACKed the payload.
Offline repeat setup/status/removal preserved unrelated configuration, comments,
credentials and user data. No owned Hermes-venv process remained after cleanup.

Artifacts: `%TEMP%\pytest-of-I347041\pytest-6372\test_released_hermes_idle_rela0`
(`provider-requests.json`, `relay-calls.json`, host/driver logs and disposable DBs).
Pinned Hermes source: `d923a5eb487a17c0a68801bba9ef0f56c81040a8`.
Installed plugin SHA-256:
`5883e2f003d605b9c4f480bef77f0921d85b42510291372a0015b1240d15e4d5`;
bridge SHA-256:
`c27491c90ab4e5fb2b0f353dc191ac53a7cd63dcdb90880218a55bab65173567`.
Parent verified these and every installed skill hash against current source.
After the pass, only explicit no-barrier-error/two-arrival assertions were added;
syntax compiled and captured evidence satisfies both without another native run.

Whole-change selector requires `python -m pytest tests/ -x -q`. Authoritative
hosted results are the `test` matrix checks on
[draft PR #321](https://github.com/rore/Pallium/pull/321); PR CI installs declared
compatible dependencies. The local full-suite request is on hold to avoid a
duplicate run. If a local run becomes necessary, shared AnyIO 4.12.1 is
incompatible and requires the existing child-only TEMP 4.14.2 overlay, not a
shared dependency update. Import boundaries: zero violations. Redline: High, architecture/API
shadow checkpoints and whole-stack size warning (25 non-record files, 4,173
changed lines); no protected behavior contract edits or boundary violations.
The workflow's commit-order advisory includes inherited slice-1 commits; this
slice's record checkpoint `31e11b15` precedes its application edits at `e25f73df`.
Slot request `relay-msg-c46e71b504ab4361ac50e067307056b1` was sent to authorized
`@astra-reviewer`; queued/ACKed transport does not allocate a slot. Follow-up
`relay-msg-c0d039db0d194c4f8221a95d03b15427` holds that request while hosted CI runs.

## Result review

Agent technical review: /root/hermes_e2e_review, 2026-10-19, accepted the code for
the frozen offline disposable-profile experiment after the installer validation,
writer-contract and skill corrections. No remaining actionable code blocker.
Reviewed revision: e25f73df plus the inspected corrective diff in setup_hermes.py,
README, mcp_bridge.py, skill/wait guidance and corresponding setup tests.
Verification adequacy: focused code/stdio tests and actual MCP SDK interoperability
support the narrow code verdict. The full non-slow suite and separate human
result review still gate overall completion.

Review verified per-call middleware identity in metadata, server-side fixed scope
and self-identity checks, private admission receipts, host-session revalidation,
context reset, exact tool catalog and unchanged default registration. Offline
exclusive profile access is the accepted setup boundary; the writer's digest
check is not atomic CAS. No production or overlapping-config-writer claim.

Incremental agent technical review: /root/hermes_e2e_review, 2026-10-19, accepted
the final native harness and pytest-6372 artifacts. Reviewed revision: application
`c250aec2` plus the native-test diff recorded with this evidence. No actionable
harness gap remains. Verification adequacy: production install/use/removal,
installed skill, real MCP catalog/discovery/send/reply, two overlapping host
conversations, attribution, provider-before-ACK-before-reply ordering, private
receipt exclusion, delivered state reads and negative controls support the narrow
frozen-profile outcome. Reviewer independently checked source/artifact pinning,
event order, zero private-value leaks and removed package files. Unchanged
application review is reused; the post-pass assertion-only addition is discharged
by saved evidence and syntax compilation. High risk and the size advisory remain;
this does not replace the full-suite or separate human review gates.

## Recovery

Owner: this chat. Branch `feat/hermes-package-slice2`; pushed implementation/native
checkpoint `a43f66707c6b352df2d2630c8cef0d38013c02a1`. Draft PR #321 is open against
main. First remaining action: inspect its hosted full non-slow test checks, fix
failures if present, and obtain separate human result review. Do not start a
duplicate local full suite without an allocated slot and compatible overlay.
The full feature stays in progress; History, optional memory, recovery and broad
host/provider support remain future slices. Retain this worktree for concrete
validation/review; do not install it into everyday use. No live setup is authorized.

Skill feedback trigger 2 dropped: review corrected application/test implementation,
not an Agent Workflow instruction or product defect.

