# Make OpenCode Relay wake refusals traceable

<!-- agent-workflow:start -->
**Outcome:**
An OpenCode wake refusal identifies the exact delivery and distinguishes a failed lookup from a response without matching work.

**Target:**
OpenCode V2 context hook, Node caller tests, and `tests/test_opencode_native_wake_e2e.py`.

**Scope:**
Change the two ambiguous wake errors and extend their existing caller-surface tests in `integrations/opencode/tests/v2-plugin.test.mjs` and `tests/test_opencode_native_wake_e2e.py`.

**Constraints:**
Keep the synthetic marker, claim and ACK authority, retries, and native input lifecycle unchanged. Only use the validated delivery ID bound to the current wake; do not expose raw HTTP details, payloads, receipts, tokens, or untrusted marker values.

**Completion criteria:**
The failed-lookup and no-matching-delivery errors are distinct and show the full validated delivery ID. Unproven markers cannot produce the diagnostic. Delayed wakes still cannot attach or ACK work already consumed by another turn.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"An OpenCode wake refusal identifies the exact delivery and distinguishes a failed lookup from a response without matching work.","scope":"Change the two ambiguous wake errors and extend their existing caller-surface tests in `integrations/opencode/tests/v2-plugin.test.mjs` and `tests/test_opencode_native_wake_e2e.py`.","constraints":"Keep the synthetic marker, claim and ACK authority, retries, and native input lifecycle unchanged. Only use the validated delivery ID bound to the current wake; do not expose raw HTTP details, payloads, receipts, tokens, or untrusted marker values.","completion_criteria":"The failed-lookup and no-matching-delivery errors are distinct and show the full validated delivery ID. Unproven markers cannot produce the diagnostic. Delayed wakes still cannot attach or ACK work already consumed by another turn."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":[]}

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
The integration source is unclassified by Redline; the change is limited to diagnostics for two existing throw sites.

**Discovery:**
The OpenCode context hook throws the same message for two distinct branches. Field evidence includes both a failed lookup and a late wake whose delivery was already ACKed. Both branches have exact native-input binding and a validated delivery ID captured in frozen request fields.

**Material assumptions:**
The host surfaces the thrown message. If it sanitizes or drops the text, stop and verify the caller surface before widening scope. No new custody or transport classification is needed.

**Plan:**
Keep both guards and change only their error strings. Use the already captured delivery ID. Extend the existing Node caller cases and the delayed-wake real-HTTP regression. Do not treat an empty response as proof that a delivery was consumed.

**Verification plan:**
Run focused tests first and the affected plugin tests. Assert distinct errors, exact ID, no arbitrary response detail, and unchanged fail-closed behavior for unproven or overtaken wakes. Run the whole-change selector before PR and preserve ordinary platform gates.

**Plan review:**
Agent technical review: independent architect approved the bounded plan. Name the existing HTTP file explicitly, use the frozen delivery ID only, and keep the two branches and all authority checks unchanged. The caller tests do not establish installed host rendering.

**Approvals:**
Not required at this risk level.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

The Node caller assertions failed on base with the old shared message in
all five changed cases; both continuation controls passed. Only the two
error strings changed, using the frozen delivery ID.

## Evidence

Eight focused Node cases passed, including forged metadata, the mismatch
with an unrelated response ID, and the two unchanged continuation controls.
The delayed-wake real HTTP regression passed in 7.15 seconds with the full
ID and existing custody and progress assertions. The selector returned
the full lane.

The affected Node file finished with 264 passes and one failure in the
unchanged `newer-candidate` supersession fixture. The full non-slow run
stopped after 4,175 passes on the unchanged Codex prompt-startup-delay
test, which exited nonzero around its eight-second bound. Neither run
is green. Keep both receipts and track those failures separately; do
not repeat the broad local runs. No coverage or timing change in this PR.

## Result review

Agent technical review: the independent architect approved the current
two-string production delta and its tests with no material findings.
Reviewed revision: `a5cb7acd` plus the isolated diagnostic diff.
Verification adequacy: adequate for both diagnostic branches and the
privacy boundary; full validation and installed rendering remain separate.
