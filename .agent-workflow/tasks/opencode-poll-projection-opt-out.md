# Let OpenCode V2 polls skip activation projection

<!-- agent-workflow:start -->
**Outcome:** OpenCode V2 polls explicitly skip activation projection when the server supports the opt-out, while continuing to work with the previous server.

**Target:** Pallium `POST /relay/opencode/wake` and its OpenCode V2 caller, composed onto `e73531d8057a16ae7dbfd6df5bf2b0c57e1e3d99` (#441). The original plan and validation used `cfb5b5ae876e96a3c9aada8b461e43af8a7f60fa`.

**Scope:** Poll-only `include_activation=false` query handling in `api/routes.py`, V2 request construction in `integrations/opencode/.opencode/plugins/pallium-v2.mjs`, the existing HTTP API docs, and affected offline HTTP and JS tests.

**Constraints:** Keep default POST and GET activation responses, strict JSON body validation, poll cadence, owner heartbeat, exact reservation, mutations, and caller error handling unchanged. The isolated implementation and planned tests are authorized. The manager owns publication after independent result review and the normal checks. No live traffic, installation, or dependency changes in this implementation task.

**Completion criteria:** 1. Default and explicit opt-in polls, non-poll mutations, and GET activation retain their existing response contracts. 2. An opted-out poll differs only in session activation and uses one wake-runner admission instead of two, with identical durable poll state. 3. Both V2 poll call sites opt out and work with projected and unprojected responses; the previous server accepts the new URL. 4. Native fixture gates still observe the same requests and forward the query.

**Requirement baseline:**
{"source":"Pallium Relay: opencode-poll-projection-opt-out-work-record","outcome":"OpenCode V2 polls explicitly skip activation projection when the server supports the opt-out, while continuing to work with the previous server.","scope":"Poll-only `include_activation=false` query handling in `api/routes.py`, V2 request construction in `integrations/opencode/.opencode/plugins/pallium-v2.mjs`, the existing HTTP API docs, and affected offline HTTP and JS tests.","constraints":"Keep default POST and GET activation responses, strict JSON body validation, poll cadence, owner heartbeat, exact reservation, mutations, and caller error handling unchanged. No live traffic, installation, dependency changes, publication, or source edits under the plan-only assignment.","completion_criteria":"1. Default and explicit opt-in polls, non-poll mutations, and GET activation retain their existing response contracts. 2. An opted-out poll differs only in session activation and uses one wake-runner admission instead of two, with identical durable poll state. 3. Both V2 poll call sites opt out and work with projected and unprojected responses; the previous server accepts the new URL. 4. Native fixture gates still observe the same requests and forward the query."}

**Behavior changes:**
[{"target":"task-context.constraints","classification":"equivalent","before":"Keep default POST and GET activation responses, strict JSON body validation, poll cadence, owner heartbeat, exact reservation, mutations, and caller error handling unchanged. No live traffic, installation, dependency changes, publication, or source edits under the plan-only assignment.","after":"Keep default POST and GET activation responses, strict JSON body validation, poll cadence, owner heartbeat, exact reservation, mutations, and caller error handling unchanged. The isolated implementation and planned tests are authorized. The manager owns publication after independent result review and the normal checks. No live traffic, installation, or dependency changes in this implementation task.","reason":"Advance the exact independently reviewed plan from drafting to isolated implementation under the task owner's approval. The product requirements and installed-environment limits are unchanged."}]

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:** `api/routes.py` is an API-contract red zone and triggers `api-review`. The narrow route change crosses client/server versions and native test proxies. The remaining intended paths (`docs/http-api.md`, `tests/test_opencode_relay_wake_e2e.py`, `tests/test_opencode_native_wake_e2e.py`, `integrations/opencode/tests/v2-plugin.test.mjs`, the V2 plugin, and this Work Record) are blue or unclassified. No protected behavior-contract paths or layer boundary changes are planned. The intended whole change is non-exempt.

**Discovery:** The current request model (`api/schemas.py:958`) forbids extra JSON fields. The route (`api/routes.py:1063`) runs the durable poll and its activation projection as separate `_relay_call`s, both on the same wake runner. Projection reads the current OpenCode owner via `app/dependencies.py:821` and `storage/sqlite_relay.py:529`; poll's own transaction renews the 15-second lease, updates `last_seen_at`, and handles exact reservation (`storage/sqlite_relay.py:468–527`). `pallium-v2.mjs:411` reads the session and wake for fresh-witness settlement; `:487` reads the same fields for the scheduled poll, including re-enroll on the existing specific 409. Neither reads activation. Enroll and context have separate readers; admitted, terminal, and detach discard the body. No other production wake-response readers were found in the repository. The common transport (`pallium-common.mjs:527`) already accepts a query in the POST path.

**Material assumptions:** The unmodified server ignores the query while still validating the same body; verify with the exact base handler. The response model already renders missing session activation as `null`. Projection happens after the poll transaction and performs a separate read; skipping it removes one admission to the wake gate and shared Relay worker, not the poll's SQLite transaction or its wait. This is sufficient for the slice if the offline comparison confirms the admission count and equivalence. It does not establish live latency, throughput, stall recovery, or a change in writer contention. Stop and return to review if wire compatibility, durable state, or admissions differ from this model.

**Plan:**
1. Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. This record is the planning deliverable. Obtain and record clean-context technical/API plan review and explicit task-owner approval of the exact plan before implementation.
2. In `api/routes.py`, declare an optional string query and skip `_with_relay_activation` only when `operation == "poll"` and the query value is exactly `"false"`. Omitted, `true`, and other values keep the previous behavior; the query never enters `model_dump()` or reaches the service. Keep the existing first `_relay_call`, the response model, and all GET and non-poll paths. Document the exact query and `session.activation: null` in `docs/http-api.md`.
3. In V2's `wakeRequest`, append the query only for `poll`. Keep the JSON body, timeout, signals, error observers, cadence, and fallback unchanged. Reuse the existing transport; no capability probe, fallback request, or changes to other callers.
4. In the affected native forwarding fixtures, compare the parsed pathname for wake-specific gates, evidence capture, and response rewriting. Forward the original path including its query. Preserve the existing assertions and use the existing HTTP and JS fixtures for verification.

**Verification plan:**
- 1. Wire compatibility on the new server -> production route via in-process HTTP in `tests/test_opencode_relay_wake_e2e.py`. Assert omitted, `true`, and an unrecognized query value preserve the projected response; the body still rejects an extra `include_activation` key. Check `GET /relay/sessions` activation and representative non-poll calls with the flag, including errors, plus existing enroll/context/admitted/terminal/detach lifecycle tests. Keep existing status, retry, and stale/foreign-owner checks.
- 2. Response, durable state, and admissions -> compare omitted/`true`/`false` for idle and pending polls at the same fixed time on equivalent scratch SQLite fixtures. Assert HTTP status and the entire response agree after accounting for `session.activation` and fixture-generated IDs; verify chosen delivery, generation and native input identity within each fixture. Read back session and owner timestamps, exact reservation and delivery attempt/state, and confirm the exact context/ACK uses the reserved delivery. Instrument the real configured runner and projection callback without replacing the transaction: expected ordered admissions are poll then projection (2 wake, 0 ordinary) versus poll only (1 wake, 0 ordinary), one poll transaction in both, and one versus zero projection callbacks. Count admissions across POST only; verify GET separately.
- 3. Both client call sites and version pairs -> in `integrations/opencode/tests/v2-plugin.test.mjs`, capture query and body through the existing fetch fixture for timer and fresh-witness polls. Drive a projected old-style response and an unprojected response through the same readers; assert no extra request and no query on enroll/context/admitted/terminal/detach. Independently send the new-client URL and unchanged body through the unmodified base's real route against scratch state and assert 200 with activation.
- 4. Proxy dispatch -> use the existing coalesced settlement and capture/rebind fixture cases in `tests/test_opencode_native_wake_e2e.py`. Show that query-bearing polls still cross the held-poll gate and get captured or rewritten where expected. Verify the original request target reaches the candidate route with the query intact.
- Release checks -> after implementation is authorized, run exact focused targets serially, then affected subsystem files. Before result review or PR, apply the whole-change selector, selected full non-slow lane, JS/native checks, and Redline/Agent Workflow checks. Retain exact candidate and results for independent and task-owner result review. A published PR must also satisfy `api-review` through the policy-supported approval or `api-reviewed` label.

**Plan review:** Agent technical review: The independent architect gave technical/API GO without corrections for plan `72f8e27e1d975ca4d9d6a4fcaefb786838b2cba5` on `cfb5b5ae`. The manager verified the exact review request and verdict in the recipient’s native turn, which ended `idle succeeded`. The review confirmed that only a poll with `?include_activation=false` skips projection; strict JSON, default and GET responses, and the exact owner and reservation checks stay intact. Compare two wake-worker admissions against one, with one durable poll transaction in both cases and the same subsequent exact claim/ACK. This is a plan verdict, not a live performance result or the separate PR `api-review` checkpoint.

**Approvals:** Approved by user 2026-11-26: "you have an approval to finish this goal". This was the direct response to the request to implement the reviewed OpenCode poll-load plan and approve the final #441 result for merge. For this Work Record it authorizes the exact isolated plan `72f8e27e` and its checks.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

The route and both V2 poll callers use the approved exact query. The native test proxies match on pathname and forward the original request target. The original worktree and evidence are preserved. The separate idle-poll writer-contention plan remains parked.

The manager accepted the reviewed six source blobs and retained affected results, and relayed the architect's composition GO on `e73531d8`. The composed checkout applies the reviewed poll hunk as-is on top of #441's durable runner for the exact Codex claim. The five other reviewed blobs are identical; #441's capacity and Codex tests are unchanged from that base. The combined route blob is `ddfad6410f2f69e4b3bb66c23b6b99386fa3210b`.

## Evidence

- Focused Windows HTTP: 3 passed. Default and explicit opt-in polls each used two wake admissions; the exact opt-out used one. In both idle and pending cases the poll used one SQLite write transaction, renewed the same owner/session fields, and returned the same response apart from activation. The pending case verified the exact reservation and a single subsequent claim/ACK. Strict JSON, non-poll projection, GET activation and error controls passed.
- Focused JS: 5 passed. Scheduled and fresh-witness polls sent the query and accepted both projected and unprojected server responses. The existing context, enrollment, admission, terminal, and detach calls kept their URLs and bodies.
- Affected HTTP/Relay capacity files: 139 passed. The exact `cfb5b5ae` server snapshot accepted the new URL and unchanged body, returning HTTP 200 with projected activation (1 passed).
- Offline production-plugin outage/recovery journey passed. Its forwarding receipt contains four query-bearing polls with HTTP 200 and `session.activation: null`. This verifies query preservation through a real local fixture, but not the released-host coalesced poll gate. That test skipped because the pinned released executable was unavailable.
- The separate capture/rebind journey failed at its first assistant-capture barrier. The unmodified base reproduced the same failure at the same step. Its fixture has neither an idle row nor a prompt-hook role snapshot for that capture, both required by the existing assistant writer. Retained the candidate and base failures separately. This blocks claiming a pass for that journey.
- The initial broader JS run used the repository root instead of the package working directory: 250 passed, 87 failed, 6 skipped. Most failures were module resolution; five V2 failures also occurred. Kept that receipt. The corrected run from `integrations/opencode/` with a private profile passed: 365 passed, 7 skipped, 0 failed (exit 0). Its separate log and JUnit are retained.
- The required full non-slow Windows lane stopped with 2 failed, 2,548 passed, 3 skipped, and 1 xfailed (exit 2). `test_subprocess_qualification_admits_only_control_approved_git_blobs[None]` failed decoding `git init` output for the Unicode fixture path under CP1252. `test_codex_hook_subprocess_preserves_scope_across_startup_delay[prompt-two-second-delay]` observed hook exit 1; its cause is unverified. Both test paths match the base. The log, JUnit and hash receipt are intact, and the six tested file blobs matched before and after. No full rerun.
- Import boundaries and `git diff --check` passed. Agent Workflow reported no blocking finding; PR `api-review` is open.

### Composition on `e73531d8`

- 21 focused HTTP and capacity cases passed. They covered poll response, durable state and admissions, exact Codex one-admission behavior and phase failures, and the unchanged #441 claim/ACK cases with default poll or projection work held.
- The offline outage/recovery fixture passed again on the composed source. Its proxy forwarded four query-bearing polls and the real route returned HTTP 200 with null activation each time. Six candidate blobs and the two #441 test blobs matched before and after the checks.
- The capture/rebind fixture fails before rebind: its initial compaction has a user and assistant but no completed idle boundary or prompt-hook role snapshot. Exercising the proxy through that journey would require fixing the unrelated capture fixture across its lifecycle cases. Its base and candidate failures remain retained. The pinned released-host executable is still unavailable, and the whole-local failure above stands. No full rerun or host installation.

## Result review

Agent technical review: The independent architect verified the six
source blobs and gave technical/API GO for the exact composition
with #441, with no product correction requested.

Reviewed revision: `cfb5b5ae` plus reviewed route `9c6edbc7`, docs
`73e1f510`, plugin `a6388c20`, JS `e62abd9c`, native fixture
`68d406d7` and HTTP `6dca14b5`; composed on `e73531d8` as exact
route `ddfad641`, with the other five blobs unchanged.

Verification adequacy: The manager confirmed the composition touches
only the OpenCode wake route and leaves #441's exact Codex route and
capacity tests intact. All 21 focused composition cases and the offline
production-plugin forwarding fixture passed. The prior 365 JS passes
remain applicable by unchanged files. Evidence supports ordinary CI;
the full Windows failure and pinned-host qualification limits stand.
