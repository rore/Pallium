# Wait for the exact supersession terminal in the Node fixture

<!-- agent-workflow:start -->
**Outcome:**
The newer-candidate fixture observes the successor terminal without assuming a single 20 ms tick settles the prior asynchronous request.

**Target:**
The newer-candidate case in the OpenCode V2 caller test.

**Scope:**
Change only the newer-candidate fixture and this record.

**Constraints:**
No production, global timeout, or CI changes. Keep the exact terminal-count and no-new-prompt assertions.

**Completion criteria:**
The fixture holds the first terminal response, observes that the successor cannot settle yet, then releases it and observes exactly the expected second terminal without a replay.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"The newer-candidate fixture observes the successor terminal without assuming a single 20 ms tick settles the prior asynchronous request.","scope":"Change only the newer-candidate fixture and this record.","constraints":"No production, global timeout, or CI changes. Keep the exact terminal-count and no-new-prompt assertions.","completion_criteria":"The fixture holds the first terminal response, observes that the successor cannot settle yet, then releases it and observes exactly the expected second terminal without a replay."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:fix-opencode-plugin-reliability"}],"pull_requests":[]}

**Risk:**
Elevated

**Complexity:**
Simple

**Reason:**
The integration test path is unclassified by Redline. No product path changes.

**Discovery:**
The unchanged supersession fixture failed at `newer-candidate` under the broader Node run. The fixture's tick returns after 20 ms, while the terminal response and its owner cleanup can still be in flight.

**Material assumptions:**
Once the first reply is released, ordinary poll ticks can observe the successor's terminal. If the exact event does not arrive under the fixture's existing five-second wait bound, stop and investigate rather than extending the wait or weakening the assertions.

**Plan:**
Use the existing fixture barrier to hold the first response. Preserve the exact count while it is held, release, then drive ordinary ticks until the expected successor terminal is observed or the existing fixture bound expires. Leave the other cases unchanged.

**Verification plan:**
Demonstrate the original single-tick expectation fails with a held response. Run the exact supersession test after correction. Select the whole-change lane before publication. No repeat of either previous broad run.

**Plan review:**
Agent technical review: the independently approved roadmap follow-up specifies a controlled delayed completion, an exact observable wait, and preservation of the no-replay and terminal-count checks. This plan follows those limits.

**Approvals:**
Not required at this risk level.

**State:** Ready for review
<!-- agent-workflow:end -->

## Evidence

Holding the first reply reproduced the old `newer-candidate` failure
deterministically: one terminal instead of two. Releasing it and driving
the fixture until the exact `msg_settled_2` request made the same focused
test pass. The terminal-count and no-new-prompt assertions remain.

The required local non-slow run stopped after 3,750 passes and one
failure. In the unchanged Codex retained-wake case, the reservation
failed at `late_begin` after setup PRAGMA work took 663 ms, before the
test reached its malformed-state rejection path. The test blob was
unchanged during the run. Keep the original failed result and do not
repeat the broad local run. The failure does not qualify the Codex path.

## Result review

Agent technical review: independent architect approved the test-only change
with no blocking findings.
Reviewed revision: `554b4ca6` plus test blob `81b93f0ad290`.
Verification adequacy: the held response proves the old assertion can read
early; the exact successor ID, count, and no-prompt assertions still reject
missing work or replay. This does not establish backend custody or platform
qualification. The selected local full lane ran and failed as recorded
above; hosted validation remains separate.
