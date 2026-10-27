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

**Plan review:** Agent technical review: astra-reviewer turn01a17d83-3a3f-7b52-8ba2-375c79734788, PLAN GO at base033f6f03. Parse only opted-in error bodies under the existing deadline, classify after complete JSON and an abort recheck, swallow observer exceptions, preserve legacy null/body cancellation. Keep registration-loss classification local to one poll; recheck native ownership/liveness before enrollment. The409 detail includes owner/location/generation mismatch as well as absent/expired ownership; existing server fences remain authoritative.

**Approvals:** Manager explicitly authorized isolated reproduction and the smallest justified correction. No new live installation or reload approval exists for this separate OpenCode change.

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Created before tests or production edits on feat/opencode-poll-transient-recovery at current origin/main033f6f033333a63b2f2fef10892bc7b8719a022f. PR367 and its installed rollout evidence remain on feat/retained-ready-retry, last local record commit20bfd082; this branch excludes that unmerged READY change. No live environment mutation.

RED: existing plugin caller fixture issued a second enrollment for both HTTP503 and the real6000ms request abort. Both new tests failed2-versus1 enrollment count before production edits; full output build/opencode-poll-transient-recovery/red.log. No harness timing or production deadline was shortened.

Implemented only the optional shared-helper HTTP-error observer and the caller-local explicit409 classification. Complete error JSON is parsed under the original request deadline; abort is rechecked before synchronous observation, observer/read exceptions retain null, and body cleanup still runs. Initial enrollment is unchanged. Poll performs its original live check, and reenrollment still rechecks native ownership and server authority. No server/API, interval, lease, capacity, global cache or installed change.

## Focused verification and remaining gates

Twelve targeted plugin/helper cases passed in6.90s: transient503 and real6000ms abort, later successful poll without enrollment, exact registration conflict, other409/404, malformed/truncated/unreadable errors, competing-owner refusal, observer exception, late error body after deadline, and retirement during body consumption. Existing hook/context/native-call surfaces are exercised with controlled HTTP responses; native installed transport is not qualified by these tests.

The required npm test entrypoint passed157 tests,7 existing skips,0 failures in41.15s, including unchanged V1 and V2 lifecycle coverage. Initial direct-node sandbox execution is retained at package.log:149 passed,8 failed,7 skipped, including explicit npm-entrypoint assertion, failed temporary git init and missing private profile pins. The corrected native npm invocation changed only runner permissions/entrypoint, not source or assertions; package-native.log is the successful receipt.

Eight existing real HTTP tests passed in3.97s using the existing isolated qualification runtime: owner lease expiry/rebind, six wrong binding fields, and detach/reenroll with the same anchor. backend-private.log is the receipt. Prior setup-only failures are retained: installed interpreter has no pytest (backend.log), then the first private-runtime attempt omitted the parent of pytest basetemp (eight setup errors, backend-native.log); no test body or production assertion ran in those attempts. Creating a new short private parent corrected that runner error without dependency or source changes.

The whole-change selector selects FULL. Broad Python validation, final result acceptance, PR/CI and any live deployment remain outstanding; manager explicitly prioritized focused incident work and source/focused review before a broader validation campaign. State Blocked records those incomplete gates, not a source test failure or a missing implementation approval. Current source is ready for the existing Astra's bounded technical source/focused assessment, with that qualification limit explicit.

Logs are retained in build/opencode-poll-transient-recovery/. Installed native source3792 continued reconnecting, but live request/status latency and the original FIFO sentinel remain independently open in retained-ready-retry and manager monitoring. Dashboard one-read evidence13:29:55UTC found overview533ms, recent sessions945ms and messages2135ms; the UI awaits all three before rendering. Neither this sample nor the OpenCode correction proves the historical latency cause. No new live write/reload/restart or synthetic message occurred.

## Source and focused result review

Agent technical review: astra-reviewer turn01a17d90-c1f9-7850-925d-bde1b767cee7, SOURCE/FOCUSED GO at4454157a26f622a3da30e116143fbde856fb4da7 against033f6f03. Reviewer inspected actual helper/V2/test diffs and retained receipts, with no material blocking finding. Optional observer preserves legacy no-error-body-read/null cleanup; local exact409 classification and unchanged live/native/server fences remain intact. No generalized retry, cache, configuration or server change.

Verification adequacy:12 focused caller/helper cases,157 npm passes with7 existing skips, and8 existing real HTTP lifecycle cases support this bounded correction. The competing-owner plugin test respects a mocked refusal; unchanged server tests/source carry its binding authority, not a new installed proof. Broad FULL selector qualification, final result acceptance/PR/CI and any deployment remain outstanding. Reviewer ran no tests and made no changes. Manager received the exact commit and limits; no live application is implied by this review.
