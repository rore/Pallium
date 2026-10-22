# Local Hermes rollout

Private installation paths, configuration, credentials and runtime receipts stay in ignored local build evidence, never public documentation or PRs.

<!-- agent-workflow:start -->
**Outcome:** Make the existing user-selected Hermes profile usable with the merged Pallium integration through a recoverable local rollout.

**Target:** Installed Pallium service and the selected existing Hermes profile.

**Scope:** This operational Work Record; isolated preflight and private backups; update the stable Pallium checkout to a reviewed merged revision; supported service restart; install the existing Hermes plugin, skill and profile-scoped MCP package; verify and, if needed, roll back only those changes. No product implementation is proposed.

**Constraints:** Preserve the primary dirty development checkout, unrelated integrations and profiles, provider configuration, credentials, data, host versions, native launch/update paths and persistent environment. No Hermes upgrade, global dependency changes, data purge, retention repair or uncertain-message resend. Use existing reviewed code and compatible interpreters. Keep private work settings out of tracked records and public communications. Coordinate the shared service outage; preserve a paired stopped database snapshot and recoverable code/config baseline before mutations. No live step before exact authority, technical review and rollback readiness.

**Completion criteria:** Preflight identifies exact source/runtime/profile and existing installation conflicts without side effects. A verified private backup and rollback preserve the original service and profile. The selected profile contains the owned plugin, skill and MCP configuration without unrelated changes. Normal supported launch works; a real attributed Relay message/reply and later-session History search/expansion work. Shared service health, status and queue health satisfy their documented contracts; unchanged integrations remain configured. Actual limits and evidence are recorded without claiming unobserved model action or native updater qualification.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Make the existing user-selected Hermes profile usable with the merged Pallium integration through a recoverable local rollout.","scope":"This operational Work Record; isolated preflight and private backups; update the stable Pallium checkout to a reviewed merged revision; supported service restart; install the existing Hermes plugin, skill and profile-scoped MCP package; verify and, if needed, roll back only those changes. No product implementation is proposed.","constraints":"Preserve the primary dirty development checkout, unrelated integrations and profiles, provider configuration, credentials, data, host versions, native launch/update paths and persistent environment. No Hermes upgrade, global dependency changes, data purge, retention repair or uncertain-message resend. Use existing reviewed code and compatible interpreters. Keep private work settings out of tracked records and public communications. Coordinate the shared service outage; preserve a paired stopped database snapshot and recoverable code/config baseline before mutations. No live step before exact authority, technical review and rollback readiness.","completion_criteria":"Preflight identifies exact source/runtime/profile and existing installation conflicts without side effects. A verified private backup and rollback preserve the original service and profile. The selected profile contains the owned plugin, skill and MCP configuration without unrelated changes. Normal supported launch works; a real attributed Relay message/reply and later-session History search/expansion work. Shared service health, status and queue health satisfy their documented contracts; unchanged integrations remain configured. Actual limits and evidence are recorded without claiming unobserved model action or native updater qualification."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:** Live shared-service deployment, persistent database compatibility and profile configuration require controlled downtime, independent judgment and recoverable backups. Repository source edits are restricted to this record.

**Discovery:** The installed service predates Hermes runtime admission and the packaged MCP adapter; a profile-only install cannot work. The existing selected profile has no Pallium-owned package. Existing Hermes MCP SDK2 and Pallium SDK1 environments are present. Hermes Desktop is running. The merged integration and scoped regressions have accepted independent evidence; local Hermes release/runtime compatibility, exact profile scope, database transition and launch verification remain to be established. Manager confirms no earlier installed rollout is approved or owned.

**Material assumptions:** The installed checkout is clean enough for a recoverable fast-forward; otherwise preserve and inspect before choosing a transition. Existing dependencies satisfy the merged runtime; otherwise stage compatible dependencies in isolation and present any required installed change explicitly. Required Hermes public capabilities are present in the actual runtime; static metadata alone is not execution proof. The current database pair is compatible or has a reviewed reversible snapshot/migration; unknown schemas fail closed. Fixed private History scope must be deliberate and cannot be inferred from cwd. Stop on source/identity conflicts, unowned profile files, unsafe host changes or unexplained readiness failure.

**Plan:** Invoke Agent Workflow, evaluate whole-change applicability and classify before implementation. Reuse the clean isolated task checkout and accepted unchanged-application review. Inspect live provenance and private state read-only; prepare exact candidate, compatible runtime paths, ownership/config delta, paired backup and rollback. Get clean-context independent review of the local transition and resolve any materially uncovered human decision. Coordinate with the manager, stop the shared service only through the supported wrapper and preserve a stopped coherent database/config/code baseline. Preserve every existing installed skill-refresh file in a verified external raw backup and an explicit-path recovery stash; fast-forward the clean installed source to the exact reviewed merged candidate, restore the seven existing divergent guidance/governance files and retain the stash. Never reset, clean or automatically reapply it. Restart with scripts/restart-service.ps1 and validate all three health surfaces. Failure rollback restores compatible old code and the exact dirty skill baseline while retaining current databases; database snapshot restoration after new writes requires a separate explicit data-loss/reconciliation decision. Quiesce the selected Hermes profile only after confirming safe timing and exact private History scope, back up its configuration, use supported package setup and preserve all unrelated settings. Verify normal launch, package ownership, tool discovery, real Relay round trip and History lookup. Keep shared reliability failures owner-routed and retain evidence.

**Verification plan:**
- Safe exact transition -> private provenance/path/hash inventory, clean installed-source check, dependency comparison, independent technical plan review, explicit authority and versioned paired backup/rollback rehearsal on isolated copies.
- Correct profile-only package -> existing setup/status ownership checks, before/after semantic config diff, plugin/skill fingerprints, unchanged unrelated profile/runtime/provider artifacts.
- Working integration -> actual selected-host launch and tool discovery, unique synthetic attributed Relay send/reply, observed History capture then search/expand from a later scoped session; distinguish scheduling, receipt and completion.
- Shared service and rollback safety -> supported wrapper plus /health, /status and /debug/queue/health; retained original code/config/database provenance, unchanged integration configuration and independent result assessment.

**Plan review:** Agent technical review: /root/hermes_route_review, clean-context nonimplementer. Service-only technical GO for exact candidate5d167936 after inspecting the Work Record, installed-to-candidate source delta, seven-file existing overlay, source-preservation/rollback rehearsal, storage compatibility/integrity and isolated profile lifecycle. No new production dependency/schema transition. Preserve all70raw files; retain explicit recovery stash and stopped paired snapshot. This clearance excludes closing Hermes Desktop or choosing/writing the private profile scope; those missing human choices gate the profile portion. Existing application acceptance is reused only for identical source, not as a claim of unchanged behavior across every shared integration.

**Approvals:** Approved by user 2026-10-22: "ok, so let's update what is needed so we can use hermes". This follows the disclosed shared-service prerequisite and selection of the existing target profile. It authorizes necessary update preparation and the described scoped rollout, not unrelated host/dependency/data changes. Any materially uncovered database or host change requires its exact impact to be surfaced before action.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Workflow invoked and non-exempt operational record created before installation edits. BLUE repository-record surface is raised to High for live operational consequences. Reused the clean isolated checkout on feat/hermes-local-rollout at merged source5d167936; the primary development and installed checkouts remain unchanged. Manager notified of the new human instruction and planned coordination. No live mutation, backup, restart or host launch performed yet.

Private preflight found the installed checkout's prior separately approved skill-only refresh. All70actual changed/untracked files were fingerprinted and externally backed up byte-for-byte;63canonical blobs equal the candidate, seven existing guidance/governance overlays differ and have independent preservation GO. No production-source edits were found. The original clean-fast-forward assumption was replaced before live mutation. A disposable-clone rehearsal proved fast-forward, exact overlay preservation and recovery of old code/index/untracked/raw baseline. Its first rollback attempt refused a stale Windows clean-filter stat; the corrected attempt verified blob equality and unchanged bytes, refreshed only that index entry without staging a content change, and passed. Failed evidence remains retained.

## Evidence

Existing release and regression evidence remains in its owning records/PRs; no repeat full qualification is planned for unchanged application code. Local preflight and exact candidate evidence are being prepared privately under build/. No local readiness claim yet.

Private online rehearsal copies of both databases passed full integrity checks, and candidate then old installed storage code reopened them with unchanged schema hashes, main/Relay versions1/0 and all table counts. These online copies are explicitly not the stopped rollback generation. Existing SDK2 on a private copy of the selected configuration passed install/status/removal with unrelated mappings preserved and live config/package unchanged. The restart's prospective process cleanup matches only the existing owned service tree; no competing component or Git post-merge hook was found. Manager received the exact candidate and shared outage plan. Live service rollout is now ready; profile scope and safe Desktop quiescence remain unresolved.

## Result review

Pending local transition and verification. Blocked only for the actual technical plan, private preflight and any uncovered scope decisions; not waiting on generic reliability diagnosis.
