# Hermes integration parity

<!-- agent-workflow:start -->
**Outcome:** Hermes follows Pallium's existing integration project-resolution semantics, with no silent profile-wide project assignment; material integration divergences and their approval history are made explicit.

**Target:** Hermes plugin, MCP bridge, package setup, integration documentation and local engineering instructions.

**Scope:** Isolated implementation of session-owned cwd project resolution for Desktop and TUI across Relay, Session History and optional memory; associated setup/update compatibility and lifecycle regressions; bounded comparison with other integrations and audit of the fixed-scope decision; smallest local instruction correction preventing unapproved behavioral divergence. Existing roadmap updates remain with their owner.

**Constraints:** Keep installed service, Hermes profiles, everyday apps/configuration/data/credentials, host versions, dependencies, PATH and primary dirty checkout untouched. No paid inference. Reuse established canonical project resolution and session identity rules. Never use a background process cwd, model arguments or another session as trusted scope. Preserve project separation, existing explicit-context admission, duplicate-action fences and privacy filters. Do not narrow requirements or weaken protected tests to accommodate implementation. Report unsupported host capabilities instead of silently pinning a project. Keep private installation settings out of tracked records and public material. Shared reliability work remains independently owned.

**Completion criteria:** One Hermes profile can serve independent sessions in different working directories with correct canonical projects and no cross-project History/memory or Relay identity contamination. Supported cwd changes, reload/resume, concurrent sessions, missing/invalid/stale cwd and lifecycle cleanup have observable end-to-end regressions through plugin/MCP/HTTP caller surfaces. Setup no longer requires a profile-wide project choice for normal cwd operation and preserves unrelated configuration. A parity comparison identifies each material divergence and its disposition; original fixed-scope authority is audited without invented conclusions. Docs describe actual behavior and limits. A clean nonimplementer accepts implementation and validation; coherent work is pushed, with no live rollout inferred.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Hermes follows Pallium's existing integration project-resolution semantics, with no silent profile-wide project assignment; material integration divergences and their approval history are made explicit.","scope":"Isolated implementation of session-owned cwd project resolution for Desktop and TUI across Relay, Session History and optional memory; associated setup/update compatibility and lifecycle regressions; bounded comparison with other integrations and audit of the fixed-scope decision; smallest local instruction correction preventing unapproved behavioral divergence. Existing roadmap updates remain with their owner.","constraints":"Keep installed service, Hermes profiles, everyday apps/configuration/data/credentials, host versions, dependencies, PATH and primary dirty checkout untouched. No paid inference. Reuse established canonical project resolution and session identity rules. Never use a background process cwd, model arguments or another session as trusted scope. Preserve project separation, existing explicit-context admission, duplicate-action fences and privacy filters. Do not narrow requirements or weaken protected tests to accommodate implementation. Report unsupported host capabilities instead of silently pinning a project. Keep private installation settings out of tracked records and public material. Shared reliability work remains independently owned.","completion_criteria":"One Hermes profile can serve independent sessions in different working directories with correct canonical projects and no cross-project History/memory or Relay identity contamination. Supported cwd changes, reload/resume, concurrent sessions, missing/invalid/stale cwd and lifecycle cleanup have observable end-to-end regressions through plugin/MCP/HTTP caller surfaces. Setup no longer requires a profile-wide project choice for normal cwd operation and preserves unrelated configuration. A parity comparison identifies each material divergence and its disposition; original fixed-scope authority is audited without invented conclusions. Docs describe actual behavior and limits. A clean nonimplementer accepts implementation and validation; coherent work is pushed, with no live rollout inferred."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:** Project identity governs private capture/retrieval, MCP authority and Relay endpoint lifecycle. Paths are mainly gray/watch and test/documentation blue; judgment raises risk for scope isolation and caller-visible behavior.

**Discovery:** Current merged source5d167936 loads a profile container once in integrations/hermes/__init__.py and starts a fixed-scope bridge in integrations/hermes/mcp_bridge.py and app/mcp/hermes.py. Setup requires container-ref. Codex derives and resolves scope from trusted hook cwd. Installed Hermes source has session cwd metadata; its supported public plugin access and release compatibility are not yet established. Existing qualification proves configured-scope operation, not project-resolution parity. No exact user authorization of the fixed-profile divergence has been established. Original approval records must be audited before attributing the omission to a particular instruction or reviewer.

**Material assumptions:** A supported public Hermes API exposes authoritative cwd for the exact session; if absent or ambiguous, stop the affected design and report the concrete host gap rather than guess. Existing project canonicalization can be reused without importing another host's large runtime; inspect before extracting a shared helper. Session transitions can use existing exact endpoint/generation lifecycle; active/uncertain deliveries must remain fenced in their original project. No global storage/API change is assumed. Discovery of a protected requirement conflict or broader production boundary returns the task to planning.

**Plan:** Invoke Agent Workflow, evaluate complete applicability and classify risk before product edits. Commit this baseline first. Independently inspect actual host APIs and audit integration parity/decision history in bounded read-only work. Specify exact scope-transition, MCP-binding and setup compatibility behavior against current integrations, then obtain clean-context technical review; reuse the user's explicit correction authority for that exact scope, surfacing any new material decision. Implement the smallest supported session-owned resolution with existing canonicalization; add caller-surface isolation/lifecycle regressions and update owning guidance. Record newly found divergences without silently accepting reduced behavior. Run focused tests, selected affected checks, full non-slow lane once and workflow compliance, retaining unrelated failures with their owner. Get independent result review, reconcile roadmap through manager and push a concrete checkpoint. No local installation or service restart.

**Verification plan:**
- Correct project semantics -> compare trusted host cwd and canonical Git/worktree/non-Git/Unicode paths with existing resolver; exercise simultaneous sessions and session transitions through real caller surfaces.
- Scope isolation and lifecycle -> plugin/MCP/HTTP E2E asserts Relay endpoint generations, History search/expand and optional memory in project A/B, stale/no cwd refusal, queued/uncertain wake fencing, reload/resume and cleanup.
- Compatible packaging -> setup/status/update/uninstall on isolated profiles preserve unrelated settings, validate trusted scope mode and refuse ambiguous existing ownership/configuration.
- Honest parity and authority -> evidence-linked integration comparison and decision audit, explicit material-difference disposition, changed docs/commands verified and clean-context technical plan/result review.
- Regression safety -> scripts/test-plan.py --base origin/main, affected subsystem, full non-slow lane once and Agent Workflow/Redline checks; no everyday environment mutation.

**Plan review:** Pending clean-context technical review after bounded host/API and parity discovery; no product implementation authorized by this field yet.

**Approvals:** Approved by user 2026-10-22: "ok, now continue with fixing this". Exact desired correction follows: "hermes should work like every other integration. first, this should be aligned and we should make sure we don't have other such cases". This authorizes isolated parity correction/audit, not a new material behavior departure or local rollout.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Workflow invoked before product edits. Whole-change scope includes application/plugin/setup/instructions and is ineligible for documentation exemption. New managed worktree on exact merged5d167936 preserves the original rollout checkout and its private recovery evidence. Discovery/technical review underway; installed service and selected profile remain untouched.

## Evidence

Authoritative Minimap item-ref returned roadmap:v1:git:github.com/rore/pallium#roadmap / item:v1:add-hermes-agent-integration. Existing explicit current-session participation was verified and reused. Manager informed by Relay message relay-msg-ea7dcdaa447c40e0911fd4585cf0c08e; owner reconciliation pending.

## Result review

Pending implementation, verification and independent result review. Scope is not production-ready and no host installation is claimed.
