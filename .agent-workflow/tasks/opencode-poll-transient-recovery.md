# OpenCode poll failure recovery

<!-- agent-workflow:start -->
**Outcome:** An established OpenCode V2 owner does not issue enrollment solely after a transient poll failure; genuinely missing or expired registration still recovers.

**Target:** OpenCode V2 polling through the existing shared HTTP helper.

**Scope:** integrations/opencode/.opencode/plugins/pallium-common.mjs, integrations/opencode/.opencode/plugins/pallium-v2.mjs, their existing caller-surface tests, and this Work Record.

**Constraints:** Preserve initial enrollment, genuine missing/expired registration recovery, exact endpoint/scope/owner checks, existing lease and HTTP deadlines, per-session exclusion and shutdown. No server protocol/schema, polling configuration, concurrency framework, installed files, plugin reload, service/app restart or live message-state mutation. Historical timeout causality remains unproved.

**Completion criteria:** Existing plugin caller fixtures reproduce the redundant enrollment after established-owner HTTP503/timeout before the fix. After the correction transient failures do not enroll, ordinary later polls resume, explicit missing/expired registration recovers, unrelated conflicts remain fenced, and disposal prevents late enrollment. Affected helper/plugin lifecycle tests and independent review pass; deployment and broad service reliability remain separate.

**Requirement baseline:**
{"source":"pallium-manager bounded reproduction/fix assignment 2026-10-27","outcome":"An established OpenCode V2 owner does not issue enrollment solely after a transient poll failure; genuinely missing or expired registration still recovers.","scope":"integrations/opencode/.opencode/plugins/pallium-common.mjs, integrations/opencode/.opencode/plugins/pallium-v2.mjs, their existing caller-surface tests, and this Work Record.","constraints":"Preserve initial enrollment, genuine missing/expired registration recovery, exact endpoint/scope/owner checks, existing lease and HTTP deadlines, per-session exclusion and shutdown. No server protocol/schema, polling configuration, concurrency framework, installed files, plugin reload, service/app restart or live message-state mutation. Historical timeout causality remains unproved.","completion_criteria":"Existing plugin caller fixtures reproduce the redundant enrollment after established-owner HTTP503/timeout before the fix. After the correction transient failures do not enroll, ordinary later polls resume, explicit missing/expired registration recovers, unrelated conflicts remain fenced, and disposal prevents late enrollment. Affected helper/plugin lifecycle tests and independent review pass; deployment and broad service reliability remain separate."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Gray/unclassified integration paths set the Elevated floor. Small caller-specific retry correction with shared helper compatibility and native owner lifecycle controls; no persistence or authority change.

**Discovery:** V2 poll collapses every failed HTTP response and timeout to null, then immediately calls enroll. Server binding uses HTTP409 detail "OpenCode registration is missing or stale" for absent/expired owner; it separately rejects changed/closed scope and competing live ownership. Initial enrollment already uses its own path. Twenty live OpenCode leases and concurrent requests were observed, but aggregate13:04 logs do not establish which calls were polls versus enrollment or explain status/READY timeouts.

**Material assumptions:** The existing explicit registration-conflict response is sufficient for reenrollment; other HTTP failures or unreadable/cancelled bodies must remain unknown. If caller fixtures or source show additional legitimate registration-loss responses, reconcile before implementation. Exact scope and live-owner checks remain server-enforced. No claim that this correction fixes the historical contention incident.

**Plan:** First add RED cases through the existing plugin fixture for HTTP503 and a real bounded HTTP timeout. Add only an optional HTTP-error response observer to the existing shared relayRequest; legacy callers retain null-on-failure. Poll captures the exact HTTP409 missing/stale-registration detail locally and reenrolls only for that response, after existing liveness checks. Preserve initial enrollment and all server checks. Verify missing/expired versus unrelated errors, recovery on later poll, cancellation/shutdown and helper compatibility. Reuse existing Astra for required plan/result judgment; no new team or broad validation campaign.

**Verification plan:** Redundant writes -> pre-fix failed caller tests and post-fix request-sequence assertions for503/timeout. Registration recovery/fencing -> explicit409 and unrelated404/409/invalid response cases using existing native plugin surface. Lifecycle -> disposal/abort and later successful polling; run existing helper and V2 files plus affected OpenCode package checks. Required broader qualification remains separate from focused incident correction and any installed rollout.

**Plan review:** Pending existing independent Astra plan judgment; no test or production edit yet.

**Approvals:** Manager explicitly authorized isolated reproduction and the smallest justified correction. No new live installation or reload approval exists for this separate OpenCode change.

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Created before tests or production edits on feat/opencode-poll-transient-recovery at current origin/main033f6f033333a63b2f2fef10892bc7b8719a022f. PR367 and its installed rollout evidence remain on feat/retained-ready-retry, last local record commit20bfd082; this branch excludes that unmerged READY change. No live environment mutation.
