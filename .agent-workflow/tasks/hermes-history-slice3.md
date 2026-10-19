# Hermes slice 3: Session History

Branch: `feat/hermes-history-slice3`; base: `f0ba46470bbe3f6703ab69d9b66ca5ada962ccce`.
Owner worktree: `C:\Users\I347041\.codex\worktrees\hermes-history-slice3\Pallium`.

<!-- agent-workflow:start -->
**Outcome:**
Capture governed Hermes user and assistant turns in Pallium Session History and prove a later Hermes session can search and expand their original sources.

**Target:**
Released Hermes v0.22.2 disposable Windows profile and isolated Pallium service/data.

**Scope:**
Hermes integration plugin and bridge, dedicated Hermes MCP adapter, profile setup and bundled guidance, focused and native E2E tests, this Work Record and the Hermes roadmap feature. Reuse existing History ingestion, search and expansion contracts in isolated disposable profiles.

**Constraints:**
Keep Relay reliability work, generic queues, retry/claim/ACK/storage semantics, protected behavior tests, CI and dependencies unchanged. Preserve exact trusted host session identity, provenance, visibility, redaction and forgetting. No live installation, configuration, data or service changes, global environment changes or paid inference. Keep released Hermes v0.22.2 frozen local-stub qualification; optional derived memory remains later work. Push recoverable branch checkpoints.

**Completion criteria:**
Real released-host E2E captures user and assistant turns, then searches and expands them from a later Hermes session through packaged tools. Caller-surface tests cover duplicate capture, missing or conflicting identity, concurrent sessions, private scope, redaction/forgetting, bounds, Unicode and errors while existing Relay wake continues to work. Required checks and independent review are recorded; roadmap and support limits are aligned; the branch and reviewable PR are pushed.

**Requirement baseline:**
{"source":"user:29c4620c-d0dc-4d45-afc3-602ae966da07","outcome":"Capture governed Hermes user and assistant turns in Pallium Session History and prove a later Hermes session can search and expand their original sources.","scope":"Hermes integration plugin and bridge, dedicated Hermes MCP adapter, profile setup and bundled guidance, focused and native E2E tests, this Work Record and the Hermes roadmap feature. Reuse existing History ingestion, search and expansion contracts in isolated disposable profiles.","constraints":"Keep Relay reliability work, generic queues, retry/claim/ACK/storage semantics, protected behavior tests, CI and dependencies unchanged. Preserve exact trusted host session identity, provenance, visibility, redaction and forgetting. No live installation, configuration, data or service changes, global environment changes or paid inference. Keep released Hermes v0.22.2 frozen local-stub qualification; optional derived memory remains later work. Push recoverable branch checkpoints.","completion_criteria":"Real released-host E2E captures user and assistant turns, then searches and expands them from a later Hermes session through packaged tools. Caller-surface tests cover duplicate capture, missing or conflicting identity, concurrent sessions, private scope, redaction/forgetting, bounds, Unicode and errors while existing Relay wake continues to work. Required checks and independent review are recorded; roadmap and support limits are aligned; the branch and reviewable PR are pushed."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:**
Persistent private conversation capture and trusted MCP identity cross privacy and provenance boundaries. Keep the common History contract unchanged and review the integration independently.

**Discovery:**
Pending bounded discovery of released public Hermes completion/message hooks and existing History ingestion/MCP contracts. This baseline precedes implementation.

**Material assumptions:**
Supported public hooks expose authoritative stable message/session identity and complete user/assistant turns. If absent, stop the affected capture path and reassess rather than invent identity or patch the host. Existing History contracts can serve this integration without changing common storage or Relay reliability.

**Plan:**
1. Invoke Agent Workflow, create the Work Record and classify risk before code edits.
2. Inspect public released-host hooks and reusable History APIs using cheaper bounded discovery workers.
3. Record the minimal integration plan and obtain independent technical review before implementation.
4. Implement trusted History capture and packaged search/expand; preserve private scope and existing lifecycle semantics.
5. Prove real native capture-to-later-search/expand and caller-surface negative/privacy contracts in disposable profiles.
6. Run selected validation, independent result review, align feature notes, push checkpoints and prepare a PR. No live rollout.

**Verification plan:**
Native released-host/local-provider-stub journey verifies capture, later search and original-source expansion through actual package tools. Focused caller-surface E2E verifies identity, visibility, duplicate/error/boundary/lifecycle controls and Relay regression. Whole-change selector, required full non-slow CI, workflow and boundary checks precede review.

**Plan review:**
Pending discovery and independent technical review.

**Approvals:**
Approved by user 2026-10-19: "ok, let's start slice 3 for session history. keep it isolated from the relay reliability work, use cheaper models where it makes sense, and push the work so we don't lose it."
This approves the previously discussed History slice and isolated qualification. Live changes remain excluded.

**Exceptions:**
—

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

Initial applicability: application/integration/test changes require normal isolated workflow. No code edit yet. The external refreshed Workflow package is used for guidance without importing unrelated PR #320 changes. The exact Minimap source reference was resolved by its CLI against this worktree.

## Evidence

Pending.

## Result review

Pending.

