# Deliver same-turn OpenCode wake recovery

<!-- agent-workflow:start -->
**Outcome:** An acknowledged OpenCode wake can continue the same pending callback after temporary Pallium unavailability, using freshly restored context without another claim, ACK, prompt, or tool replay.

**Target:** OpenCode V2 Relay integration.

**Scope:** Publish and validate the independently reviewed changes to `integrations/opencode/.opencode/plugins/pallium-v2.mjs`, `integrations/opencode/tests/v2-plugin.test.mjs`, and `tests/test_opencode_native_wake_e2e.py`, plus this delivery record.

**Constraints:** Keep exact scope, owner, input, generation, delivery and attempt checks. Preserve ordinary turns and existing lease and per-request limits. No API, storage, other runtime, or live environment changes in this PR. Preserve failed validation evidence.

**Completion criteria:** Controlled 503 and connection-close journeys resume the same acknowledged turn, use fresh authority, and reach a second tool action and later work without replay. Unconfirmed or superseded work must not be restored. Hosted checks and released-host qualification remain distinct.

**Requirement baseline:**
{"source":"Task-owner authorization to deliver the reviewed OpenCode outage fix","outcome":"An acknowledged OpenCode wake can continue the same pending callback after temporary Pallium unavailability, using freshly restored context without another claim, ACK, prompt, or tool replay.","scope":"Publish and validate the independently reviewed changes to `integrations/opencode/.opencode/plugins/pallium-v2.mjs`, `integrations/opencode/tests/v2-plugin.test.mjs`, and `tests/test_opencode_native_wake_e2e.py`, plus this delivery record.","constraints":"Keep exact scope, owner, input, generation, delivery and attempt checks. Preserve ordinary turns and existing lease and per-request limits. No API, storage, other runtime, or live environment changes in this PR. Preserve failed validation evidence.","completion_criteria":"Controlled 503 and connection-close journeys resume the same acknowledged turn, use fresh authority, and reach a second tool action and later work without replay. Unconfirmed or superseded work must not be restored. Hosted checks and released-host qualification remain distinct."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Wake continuation crosses asynchronous ownership and cancellation boundaries; source and coverage require independent review.

**Discovery:** After the first ACK and tool result, a temporary failure on the next context read could stop the turn even when Pallium later restored the original delivery. Independent review caught two bootstrap issues: a wake restored mid-callback needed a guard, and the first restored response needed exact binding validation. The reviewed correction addresses both.

**Material assumptions:** A confirmed delivery identity permits a bounded read, never a new claim. Local deadline and lifetime checks do not establish that the released host will keep a callback pending for 120 seconds or signal native cancellation.

**Plan:** Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. Apply only the exact reviewed three-file patch to current main in an isolated worktree. Reuse valid focused evidence, retain the failed local full run, and run normal hosted checks on the actual PR.

**Verification plan:**
Same-turn progress and exact custody → controlled Node caller checks and real-HTTP 503/closed-connection journeys through the production plugin.
Restoration, scope and late-result fences → bootstrap, malformed binding, no-retry, and successor controls.
Whole change → selector, Redline, Agent Workflow and normal hosted checks; disclose the failed local run and do not infer installed behavior.

**Plan review:** Agent technical review: independent plan and coverage review accepted the bounded exact-context design. The follow-up source review closed both bootstrap blockers and approved narrow reuse of unchanged focused evidence. Original review evidence is retained privately.

**Approvals:** Task owner authorized submission for normal PR validation. No live installation or host reload is part of publication.

**State:** Blocked
<!-- agent-workflow:end -->

## Evidence

The reviewed source applied unchanged to `e1e5c4f3`. The whole-change
selector chose full validation. Scoped Redline returned GRAY without a
boundary violation or checkpoint; Agent Workflow returned clean before
commit. The unchanged import graph's boundary evidence was reused.

The baseline real-HTTP regression failed after the first ACK and tool step.
The first corrected run passed 102 of 104 Node cases and all eight real-HTTP
cases. After the final catch and fixture corrections, all five affected
Node cases passed. No final combined rerun is claimed.

The local full non-slow run stopped early: 3,875 passed, two failed, and one
teardown errored. The unchanged Codex session-start case stopped before
scope assertions. The unchanged Hermes transport recovery case lacked the
expected selector and did not complete its owned SDK cleanup. Both exact
cases passed in the prior local full run. This does not establish the
failure causes or a passing current full suite. Hosted validation is next.

## Result review

Agent technical review: independent correction review accepted the exact source and focused evidence reuse.
Reviewed revision: three-file source export SHA-256 `d471d5a2537a40e26929cc21c0f9ba539a68193a9f60245bd8c8329807d1c9de` applied unchanged to `e1e5c4f3`.
Verification adequacy: controlled real-HTTP and caller evidence covers same-input continuation and refusal boundaries; full local validation failed, hosted checks remain open, and released-host continuation is not yet verified.
