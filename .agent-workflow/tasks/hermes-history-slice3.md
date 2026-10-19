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
Pinned clean Hermes v0.22.2 d923a5eb exposes post_llm_call(session_id, turn_id, user_message, assistant_response, conversation_history) after transcript persistence; history rows carry host-issued logical message_uid. The callback can still run after a failed host transcript write; there is no public commit flag or committed-message read API. Captured sources are hook-observed snapshots, never evidence of host transcript persistence or message delivery. Source: agent/turn_finalizer.py:453-477,605-658; agent/message_metadata.py:27-31; tests/agent/test_context_engine_message_uid.py:148-166. Existing POST /items handles redaction and source identity deduplication; shared MCP History handlers already provide scope, paging, lookup lineage and forgetting checks. actor_ref and source_thread_ref are historical filters, distinct from current identity. No common core/API/storage edit is needed. Source forgetting tool is not added: its existing handler lacks container scope; this slice verifies externally forgotten sources stay excluded.

**Material assumptions:**
The released post_llm_call history contains current hook-observed text rows and stable host-issued logical UIDs. It does not prove the Hermes transcript committed: finalizer catches persistence errors and still calls the hook, and no public commit witness exists. Pallium stores an independently governed snapshot marked capture_stage=post_llm_call; it must never claim host commit or delivery. Require exact host IDs/UIDs and simple matching current user/final assistant rows; skip unsupported merged/hidden/scaffolding/multimodal or missing-identity rows. Synthetic Relay wake user markers are excluded; a valid final assistant row may carry relay_wake origin. No transcript backfill, interrupted-turn completeness, private host marker/DB access or provider-context capture. Caller-surface tests deliberately omit or falsify private persistence markers to ensure no hidden durability assumption. If supported identity/current-pair evidence fails, stop and reassess.

**Plan:**
1. Invoke Agent Workflow, create the immutable baseline and classify risk before code edits (done).
2. Reuse public post_llm_call in integrations/hermes/__init__.py. Select the current hook-observed user and final assistant rows after the last user boundary; retain exact host message_uid/session/turn as provenance. Stable source IDs hash only the configured container, exact session and UID, never text or timestamps. POST /items with source_type/agent_ref hermes, private fixed scope, role and artifact_kind message using the existing bounded loopback HTTP helper. Capture bounded simple text (20,000 code points), skip unsupported shapes/over-boundary input rather than silently truncate. Repeated callbacks deduplicate through the existing service identity contract; no new queue, outbox, database or retry machinery. Use the existing session/wake fence to exclude synthetic user markers and mark assistant wake-origin metadata without receipts. Metadata labels the capture stage, never host commit. Fetch optional exact work associations from GET /relay/sessions/work-refs using the trusted runtime/session/container, verify the returned session tuple and copy returned canonical work_ref keys into metadata.pallium_work_refs. Lookup errors/mismatched identity omit refs and never infer from cwd or model arguments.
3. Extend app/mcp/hermes.py and integrations/hermes/mcp_bridge.py catalogs with exactly pallium_search_history, pallium_search_history_by_work_ref and pallium_expand_source. Reuse shared handlers unchanged, bind trusted requester session/container/private visibility; hide current-identity fields. Keep actor_ref/source_thread_ref as optional historical filters, do not inject actor filter. Reject model request_source_item_id because this completion-only capture does not inject an authoritative current request source. Preserve native result/page/lookup fields and validate metadata conflicts before any HTTP call. Keep all existing Relay tools and hook ownership.
4. Update manifest, packaged skill and integrations/hermes/README.md for History scope, replay/lineage and limits; update only the Hermes feature notes after reading Minimap procedures. Setup owns the same package tree; no new configuration or launcher/dependency change.
5. Add tests/test_hermes_history.py for actual plugin-hook to HTTP caller-surface capture and real stdio search/expand. Cover duplicate/forget non-resurrection, absent/false private persistence markers, missing/conflicting identity, wrong scope, private/redaction/Unicode, positive later-session exact-work capture/search plus missing/mismatched association omission, paging/revision/lookup lineage, boundary/malformed/unavailable/unsupported input and concurrent sessions. Preserve protected contracts. Extend tests/test_hermes_relay_native_e2e.py through a distinct later actual Hermes conversation searching and expanding captured turns while retaining Relay wake and lifecycle assertions; reuse its released source/environment and local stub.
6. Run focused checks, selector and full non-slow hosted CI, independent review, align feature evidence and push checkpoints/PR. Import only merged main, no unmerged reliability work. PR #320 was explicitly approved and merged as fcea3d1b, now merged into this branch at 0471c347; it resolves the old checker relationship incompatibility without new slice-specific governance edits.
Key paths are the Hermes adapter/plugin/manifest/skill/docs and their tests. Gray integration paths and watch app/mcp/hermes.py are integration-specific; tests/roadmap/WR are blue. High privacy/identity judgment remains even without red path edits. No common contract change or forget tool exposure.

**Verification plan:**
Native released-host/local-provider-stub journey verifies capture, later search and original-source expansion through actual package tools. Focused caller-surface E2E verifies identity, visibility, duplicate/error/boundary/lifecycle controls and Relay regression. Whole-change selector, required full non-slow CI, workflow and boundary checks precede review.

**Plan review:**
Initial technical review by /root/history_plan_review at c30d947e found an unsupported host-durability claim and unspecified work-ref propagation. Both are clarified above: public hook-observed snapshots with explicit stage metadata and exact verified session association reads. Agent technical review: /root/history_plan_review, 2026-10-19, accepted on reassessment after inspecting c30d947e and pinned Hermes d923a5eb; conditions (hook-observed stage labeling, strict current-row identity, fixed private ingestion, validated optional session refs and positive/negative caller-surface evidence) are incorporated in 23d6774b. Reviewer explicitly confirms these clarifications preserve the approved baseline and require no renewed human plan approval. Existing user approval covers the History integration and isolated qualification, not live changes.

**Approvals:**
Approved by user 2026-10-19: "ok, let's start slice 3 for session history. keep it isolated from the relay reliability work, use cheaper models where it makes sense, and push the work so we don't lose it."
This approves the previously discussed History slice and isolated qualification. Live changes remain excluded.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Initial applicability: application/integration/test changes require normal isolated workflow. Application edits began only after the accepted plan checkpoint 848c3c2a. The user approved merge of the already reviewed PR #320; its merged main is now imported in this isolated branch, with no live checkout or service update. The exact Minimap source reference was resolved by its CLI against this worktree.

## Evidence

Parent focused caller-surface capture + existing Relay plugin + setup lifecycle: 95 passed, 1 skipped (Windows symlink permission), 40.83s. Private interpreter and disposable data only. The initial two fixture errors were corrected against the actual shared contracts (supported Bearer secret shape and attach response.attached); both failed nodes passed before the full affected run.
Artifacts: %TEMP%/pallium-hermes-history-slice3-01a1489e/parent-focused.{json,log}. The receipt names the planning HEAD plus dirty implementation; final code hashes/commit are required before acceptance.

First native attempt failed in the extended stub: auxiliary title requests also contained the History marker but offered no tools. A simultaneous temporary worker edit of SDK2 snake_case fields to SDK1 camelCase produced an installer source/fingerprint mismatch; status correctly refused the changed copy. Parent rejected that wrong-runtime change immediately; worker restored the qualified Hermes SDK2 contract. Production files are frozen before rerun. No host/dependency/live change occurred. This attempt is not accepted E2E evidence.


## Result review

Pending.


Discovery workers: /root/hermes_native_harness inspected pinned public Hermes source and /root/validate_hermes inspected existing History MCP/API contracts, read-only. Exact feature relationship decoded as declared; existing explicit Relay work association is reused. Worktree remains isolated and pushed.

Pre-edit risk evidence: planned-path Redline GRAY, no checkpoints, zero import boundary violations; High retained for integration privacy/identity judgment. Artifacts: %TEMP%/pallium-hermes-history-slice3-01a1489e/redline-planned.json.

Implementation may begin after independent plan acceptance. The initial user instruction approves the presented History slice; no new host commit guarantee, source-forget capability or live change is introduced.

Implemented integration-specific capture and three-tool access; no core/API/storage/Relay reliability implementation changed. Optional manager roadmap handoff relay-msg-0d793cf88e6c486e8b3f9e8053f8357a remains pending with native_unavailable; no receipt/ownership acceptance is claimed. Feature reconciliation must retain exact source association and preserve the dirty primary checkout.
