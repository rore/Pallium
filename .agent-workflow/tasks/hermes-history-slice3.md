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
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":["https://github.com/rore/Pallium/pull/322"]}

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
Hook-observed current pair and stable provenance -> tests/test_hermes_history.py public callback through POST /items and normal source context reads, including missing IDs, callback mismatch, unsupported/private persistence markers, duplicate capture, bounds and Unicode.
Private scope, redaction, forgetting and exact-work attribution -> caller-surface capture and real stdio tests in tests/test_hermes_history.py and tests/test_hermes_mcp.py, positive later-session work search plus wrong-session/unavailable association omission and tombstone replay.
Later actual Hermes search and expansion with lookup lineage -> tests/test_hermes_relay_native_e2e.py pinned released gateway/local-provider journey, distinct requester session, retained Relay wake and setup/removal assertions.
Final integration and workflow contracts -> whole-change test-plan selector, required hosted full non-slow suite, fresh import/Redline/workflow checks, protected contracts unchanged and independent result review.

**Plan review:**
Agent technical review: /root/history_plan_review, 2026-10-19. Inspected c30d947e and pinned Hermes d923a5eb; accepted the clarified design incorporated in 23d6774b before implementation checkpoint 848c3c2a. Conditions: hook-observed stage labeling, strict current-row identity, fixed private ingestion, verified optional exact-session refs and positive/negative caller-surface evidence. Initial unsupported host-durability claim and unspecified work-ref propagation were resolved by that clarification. Reviewer confirms the baseline and existing human approval remain valid; no live changes are authorized.

**Approvals:**
Approved by user 2026-10-19: "ok, let's start slice 3 for session history. keep it isolated from the relay reliability work, use cheaper models where it makes sense, and push the work so we don't lose it."
This approves the previously discussed History slice and isolated qualification. Live changes remain excluded.

**Exceptions:**
—

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Initial applicability: application/integration/test changes require normal isolated workflow. Application edits began only after the accepted plan checkpoint 848c3c2a. The user approved merge of the already reviewed PR #320; its merged main is now imported in this isolated branch, with no live checkout or service update. The exact Minimap source reference was resolved by its CLI against this worktree.

## Evidence

Parent focused caller-surface capture + existing Relay plugin + setup lifecycle: 95 passed, 1 skipped (Windows symlink permission), 40.83s. Private interpreter and disposable data only. The initial two fixture errors were corrected against the actual shared contracts (supported Bearer secret shape and attach response.attached); both failed nodes passed before the full affected run.
Artifacts: %TEMP%/pallium-hermes-history-slice3-01a1489e/parent-focused.{json,log}. The receipt names the planning HEAD plus dirty implementation; final code hashes/commit are required before acceptance.

First native attempt failed in the extended stub: auxiliary title requests also contained the History marker but offered no tools. A simultaneous temporary worker edit of SDK2 snake_case fields to SDK1 camelCase produced an installer source/fingerprint mismatch; status correctly refused the changed copy. Parent rejected that wrong-runtime change immediately; worker restored the qualified Hermes SDK2 contract. Production files are frozen before rerun. No host/dependency/live change occurred. This attempt is not accepted E2E evidence.


## Result review

Agent technical review: /root/history_plan_review, 2026-10-19, independent non-implementer. Accepted the full production/caller-surface/native/guidance diff at 269b32ff conditionally on final validation. The only finding was unqualified shared supported-memory expansion; reviewer accepted the five-file narrow correction committed as 016cce03, with no further finding. The guard hides the option and refuses true before HTTP without changing the shared handler.
Reviewed revision: 016cce03 (269b32ff plus the explicitly inspected correction).
Verification adequacy: caller-surface hook/HTTP and real stdio tests cover the significant provenance, private scope, redaction, forgetting/replay, work-ref, paging and identity risks; actual released-host later-session search/expand plus retained Relay/lifecycle journey proves the native boundary. Focused correction rerun passed 17 tests in 9.29s. Final package native rerun passed as recorded below. Required full non-slow CI is tracked by the live checks on PR #322, which are authoritative for the latest pushed revision; at this evidence checkpoint those checks are running. Technical acceptance requires their successful completion. Separate human result review remains open; no merge/live rollout is authorized by this record.



Discovery workers: /root/hermes_native_harness inspected pinned public Hermes source and /root/validate_hermes inspected existing History MCP/API contracts, read-only. Exact feature relationship decoded as declared; existing explicit Relay work association is reused. Worktree remains isolated and pushed.

Pre-edit risk evidence: planned-path Redline GRAY, no checkpoints, zero import boundary violations; High retained for integration privacy/identity judgment. Artifacts: %TEMP%/pallium-hermes-history-slice3-01a1489e/redline-planned.json.

Implementation may begin after independent plan acceptance. The initial user instruction approves the presented History slice; no new host commit guarantee, source-forget capability or live change is introduced.

Implemented integration-specific capture and three-tool access; no core/API/storage/Relay reliability implementation changed. Optional manager roadmap handoff relay-msg-0d793cf88e6c486e8b3f9e8053f8357a remains pending with native_unavailable; no receipt/ownership acceptance is claimed. Feature reconciliation must retain exact source association and preserve the dirty primary checkout.

Native qualification checkpoint 269b32ff: 1 passed in 75.06s against clean Hermes d923a5eb. Real later conversation called search and expansion using exact source/lookup lineage and received original Unicode user/assistant content. Two same-profile Relay conversations overlapped (peak 2, no barrier error); wake/ACK ordering/reply/sender receipt and status/removal preserved unrelated config. Parent independently verified retained JSON shows 9 captured rows, one actual query and one source-context expansion. All owned processes/servers stopped. Artifacts: %TEMP%/pallium-hermes-history-slice3-01a1489e/run-native-002/test_released_hermes_idle_rela0. This precedes the narrow supported-memory guard; final frozen-package run-native-003 supersedes this checkpoint as recorded below.

Whole-change selector at 269b32ff selects full lane: python -m pytest tests/ -x -q. Hosted CI will provide the required compatible-environment full non-slow run; no duplicate local full suite. Fresh final-path Redline is GRAY with zero boundary violations. Local runtime workflow check is clean after fresh build/redline-verdict.json and correctly formatted independent plan-review evidence.

The user-requested isolation is preserved: Hermes-only feature reconciliation is proposed in this branch/PR, including merged PR321 state and slice3 scope; dirty shared primary/reliability roadmap and installed checkout stay unchanged. Manager handoff remains queued; shared checkout synchronization is not claimed. Full feature remains in-progress for optional memory, normal use and recovery qualification.

Skill feedback trigger 2 dropped: incorrect SDK runtime used by a worker test and early record-format mistakes were local implementation/test errors, not upstream Workflow defects. Corrected without changing shared policy, dependencies or installed tools.

Owning draft PR: https://github.com/rore/Pallium/pull/322. Provider-returned URL appended to Relationships and read back; source tuple remains exact. Hosted full validation is started on this PR.

Final native qualification: 1 passed in 101.11s against application/package 016cce03 and clean Hermes d923a5eb. All three History tools are exposed while include_supported_memories is absent. Actual later-session search and expansion returned original Unicode turns with exact source/lookup lineage. Existing two same-profile concurrent Relay conversations, wake/receipt/ACK/reply and install/status/reinstall/removal preservation checks passed. Owned host/driver processes and loopback servers stopped normally. Artifacts: %TEMP%/pallium-hermes-history-slice3-01a1489e/run-native-003/test_released_hermes_idle_rela0.
Final package SHA-256: plugin c5ba9faec8e57c454cb572e916d49c8a54f26b8c480e247a7138ce4d928cf41a; bridge f6c361447677f3af6a45a32f9ed2203208f6ee3c935a29f1245e228f28fb1d0b; manifest 59d9333fd9963ed7931d023eee82bbec304ff5616601eefde857ed22e4560420; skill f921a2b1a0ddae5d60e78904c39d14d53b04406a5def9816c25047df85fea5db. Installed ownership marker and source agree. No application changes follow this tested/reviewed revision; remaining publication edits are evidence/roadmap metadata only.

Independent review's focused and native conditions are discharged by 17 passed in 9.29s and the final native pass. Full compatible-environment regression and separate human result review remain PR gates. Final CI result is recorded in the owning PR's checks/description rather than triggering a second full suite merely to copy its result into a commit. Task worktree is retained for the open PR; no live rollout or shared checkout synchronization performed.
