# Hermes slice 4: production readiness

Branch: `feat/hermes-production-slice4`; initial main: `2ac9e2b66b9cd72ff7af9e7aeda9ecf061360b1f`.
Owner worktree: `C:\Users\I347041\.codex\worktrees\hermes-production-slice4\Pallium`.
Canonical item: `roadmap/features/add-hermes-agent-integration.md`.

<!-- agent-workflow:start -->
**Outcome:**
Deliver a production-ready Pallium integration for both Hermes Desktop and TUI, reusing the existing Pallium capabilities and remaining compatible across supported Hermes releases rather than one exact version.

**Target:**
Pallium's Windows Hermes Desktop and TUI integration and its qualified release matrix.

**Scope:**
Hermes plugin, bridge, manifest, bundled skill/guidance and compatibility diagnostics; Hermes setup/status/update/removal; integration-specific MCP identity/provenance adapters and shared MCP seams only when required to reuse existing tools without changing other runtimes; caller-surface and real-host E2E, lifecycle/recovery/compatibility qualification, release documentation and the Hermes roadmap item. Complete memory parity, ordinary-provider and Tool Search behavior, and supported plugin coexistence through public host APIs. Use an isolated branch, profiles, service/data and qualification environments.

**Constraints:**
Preserve the user's everyday applications, versions, credentials, settings, data, primary/installed checkouts and services; local rollout requires separately described explicit approval. Keep Relay reliability-owned work and generic scheduler/claim/ACK/storage authority isolated; coordinate shared blockers rather than fork them. Reuse common Pallium semantics, private defaults, opt-in memory, visibility, redaction, forgetting, stable provenance and retrieval-not-use invariants. No host patch, private runtime registry, forced upgrade/downgrade, global dependency/PATH change, protected-contract weakening, governance/CI edit, or paid inference without an explicit bounded approval. Respect the user's preference to ask questions directly in chat, not input widgets. Use cheaper capable workers and focused/reusable evidence; freeze source snapshots during qualification and push recoverable checkpoints.

**Completion criteria:**
A documented supported matrix covers both Desktop and TUI on Windows, ordinary provider configurations and default Tool Search, and at least two compatible released Hermes versions with public capability checks and clear unsupported-runtime diagnostics. Actual native E2E proves bundled skill/tools, Relay round trips, History capture/later search/expansion, configured optional memory lifecycle and memory-disabled independence with correct trusted identity/privacy. Caller-surface and native recovery checks cover busy/concurrent sessions, reset/close, host/service/MCP restart, stale routing and ambiguous admission/ACK without wrong-session delivery or unsafe duplicate actions. Disposable install/use/update/remove/rollback and bounded repeated-use qualification preserve unrelated data/settings and leave no owned processes; required whole-change checks and independent review pass. Publish pushed reviewable work and an evidence-based readiness verdict; report any unmet release gate explicitly instead of labeling an experimental path production-ready. Everyday installation is a separate final rollout decision.

**Requirement baseline:**
{"source":"user:eee19723-e119-46cd-a30a-35069ce3e985; user:5a101245-86d8-491e-9c0b-6686aec40e55","outcome":"Deliver a production-ready Pallium integration for both Hermes Desktop and TUI, reusing the existing Pallium capabilities and remaining compatible across supported Hermes releases rather than one exact version.","scope":"Hermes plugin, bridge, manifest, bundled skill/guidance and compatibility diagnostics; Hermes setup/status/update/removal; integration-specific MCP identity/provenance adapters and shared MCP seams only when required to reuse existing tools without changing other runtimes; caller-surface and real-host E2E, lifecycle/recovery/compatibility qualification, release documentation and the Hermes roadmap item. Complete memory parity, ordinary-provider and Tool Search behavior, and supported plugin coexistence through public host APIs. Use an isolated branch, profiles, service/data and qualification environments.","constraints":"Preserve the user's everyday applications, versions, credentials, settings, data, primary/installed checkouts and services; local rollout requires separately described explicit approval. Keep Relay reliability-owned work and generic scheduler/claim/ACK/storage authority isolated; coordinate shared blockers rather than fork them. Reuse common Pallium semantics, private defaults, opt-in memory, visibility, redaction, forgetting, stable provenance and retrieval-not-use invariants. No host patch, private runtime registry, forced upgrade/downgrade, global dependency/PATH change, protected-contract weakening, governance/CI edit, or paid inference without an explicit bounded approval. Respect the user's preference to ask questions directly in chat, not input widgets. Use cheaper capable workers and focused/reusable evidence; freeze source snapshots during qualification and push recoverable checkpoints.","completion_criteria":"A documented supported matrix covers both Desktop and TUI on Windows, ordinary provider configurations and default Tool Search, and at least two compatible released Hermes versions with public capability checks and clear unsupported-runtime diagnostics. Actual native E2E proves bundled skill/tools, Relay round trips, History capture/later search/expansion, configured optional memory lifecycle and memory-disabled independence with correct trusted identity/privacy. Caller-surface and native recovery checks cover busy/concurrent sessions, reset/close, host/service/MCP restart, stale routing and ambiguous admission/ACK without wrong-session delivery or unsafe duplicate actions. Disposable install/use/update/remove/rollback and bounded repeated-use qualification preserve unrelated data/settings and leave no owned processes; required whole-change checks and independent review pass. Publish pushed reviewable work and an evidence-based readiness verdict; report any unmet release gate explicitly instead of labeling an experimental path production-ready. Everyday installation is a separate final rollout decision."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":[]}

**Risk:** High

**Complexity:** Large

**Reason:**
Persistent private History and memory mutations, runtime identity, delivery admission and profile lifecycle span trust/data boundaries. Two host interfaces and multiple released runtimes require independently verifiable qualification.

**Discovery:**
Pending bounded public-source and existing-integration discovery. Baseline precedes application discovery and edits. Slices 1–3 are merged; current main includes subsequent owners' changes that this task must preserve.

**Material assumptions:**
Public supported host APIs can provide exact session/turn identity and safe delivery semantics for both interfaces across more than one release. If unavailable, record the specific upstream compatibility blocker and stop the affected claim rather than patch the host or promise unsupported production readiness. Ordinary providers and Tool Search must preserve host authorization and private admission receipts. User's exact preferred provider/model remains unspecified; proceed with provider-independent work and public-protocol qualification, and ask directly when a specific live-provider probe is needed.

**Plan:**
1. Invoke Agent Workflow, evaluate applicability, establish this immutable baseline and classify risk before code edits.
2. Use bounded cheaper discovery workers to map shared capability parity, public Desktop/TUI/version contracts and native recovery/lifecycle harness gaps.
3. Record the smallest concrete implementation and acceptance matrix, classify all intended paths and obtain clean-context technical plan review before application changes. Reuse the user's approved outcome/scope; surface only material uncovered decisions.
4. Implement and verify incremental integration-only contributions, reusing common tools and safe profile ownership patterns. Freeze each production snapshot while real-host qualification runs; push checkpoints.
5. Run real-host compatibility/provider/tool-discovery/recovery/lifecycle qualification with disposable data and bounded offline stubs first. Obtain exact separate approval before any paid live-provider probes or everyday environment changes.
6. Run selected/full required checks, independent result review, roadmap reconciliation and a readiness verdict. Publish the reviewable result and preserve source/evidence. No automatic live promotion or main merge beyond existing explicit authorization.

**Verification plan:**
Shared full-package parity and private defaults -> public MCP/HTTP/hook E2E for Relay, History and optional memory on/off, comparing existing runtime contracts.
Both interfaces and multiple releases -> actual Desktop and TUI journeys on recorded released builds plus public capability/refusal tests; do not count gateway-only evidence as Desktop UI validation.
Recovery and duplicate/data-safety boundaries -> native and caller-surface fault/reset/concurrency tests through normal state reads and traces, preserving reliability ownership.
Profile lifecycle and repeat use -> disposable setup/status/update/remove/rollback, conflict preservation, bounded soak and owned-process cleanup.
Production claim -> explicit support matrix, test-plan-selected full CI, boundary/workflow checks and independent review; each unmet gate remains visible.

**Plan review:**
Pending discovery and clean-context technical review.

**Approvals:**
Approved by user 2026-10-20: "i want to get to a production ready state so that i can finally use it, so if you need extend slice 4 to include all that is needed to get this integration to production readiness"
Approved by user 2026-10-20: "we should support both desktop and tui. also make sure we're not bound to a single hermes version."
These approve isolated implementation and qualification within this scope. They do not approve live environment changes, unbounded paid inference or forced host changes.

**Exceptions:**
—

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

Whole-change applicability is normal workflow: integration, setup and MCP/runtime paths are not a documentation-only exemption. No application edits yet. Primary checkout's unrelated dirty Work Record and Relay/OpenCode roadmap files are preserved. Initial worktree creation lacked the newly released main object; fetched the verified origin/main and created this isolated worktree without changing primary HEAD/files. Existing explicit exact-feature Relay association is reused from a successful tool list; no duplicate attach.

## Evidence

Pending.

## Result review

Pending.

