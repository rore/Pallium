# Make a missed wake easier to diagnose

<!-- agent-workflow:start -->
**Outcome:** A person seeing a refused OpenCode wake restore can look up the intended delivery without guessing.
**Target:** OpenCode V2 wake error shown to the caller.
**Scope:** One existing error, its existing plugin test, and the triage paragraph in docs/agent-relay.md.
**Constraints:** Keep delivery, wake, retry and ACK behavior unchanged. Use the existing trace; no new storage, service, event or periodic check.
**Completion criteria:** The refusal identifies the original delivery even when the response names another. The existing trace guide explains what to do with that ID, including when no evidence is available.
**Requirement baseline:**
{"source":"work-record-initial","outcome":"A person seeing a refused OpenCode wake restore can look up the intended delivery without guessing.","scope":"One existing error, its existing plugin test, and the triage paragraph in docs/agent-relay.md.","constraints":"Keep delivery, wake, retry and ACK behavior unchanged. Use the existing trace; no new storage, service, event or periodic check.","completion_criteria":"The refusal identifies the original delivery even when the response names another. The existing trace guide explains what to do with that ID, including when no evidence is available."}
**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:fix-opencode-plugin-reliability"}],"pull_requests":[]}
**Risk:** Elevated
**Complexity:** Simple
**Reason:** The plugin is an integration boundary. The proposed change is limited to the text of one verified wake error.
**Discovery:** At `332cd733`, `reservedWake()` checks the current input against the local wake. `fields.delivery_id` freezes that ID before the context request. Two neighboring errors already show it. The restored-authority refusal does not. The existing `wake-delivery` test supplies a mismatched response ID.
**Material assumptions:** The trace may be unavailable or contain no native evidence. Neither condition justifies guessing the cause, resending the message or resetting the session.
**Plan:** Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit. Reuse this record. In `integrations/opencode/.opencode/plugins/pallium-v2.mjs`, append the frozen local ID to the restored-authority refusal. Shorten the search for operator guidance by putting the error example beside the existing trace command. Leave the refusal itself in place.
**Verification plan:** In `integrations/opencode/tests/v2-plugin.test.mjs`, extend the existing mismatched-delivery case: the error must name the original ID, never the response ID. Retain its checks that no unverified content is attached or replayed. Reuse the existing trace tests; run the affected plugin tests and the repository's whole-change selector before publication.
**Plan review:** Agent technical review: independent read-only GO. The reviewer checked the task record, plugin, test and trace guide. The frozen local ID identifies the intended delivery even when the response names another. The reviewer found no need to expand scope. A standalone workflow SPEC.md was not available in this checkout.
**Approvals:** Not required at this risk level. Implementation of the reviewed scope was assigned through Pallium Relay; no live operation.
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation and verification

The existing refusal now names the frozen input's delivery ID, not
the response's ID. The trace guide explains how to interpret an ACK or
an unavailable trace without replay. No wake, retry, claim or ACK
logic changed.

The mismatched-delivery test failed before the change because the
error had no ID. Afterward it and the valid restore control passed.
The Relay guidance checks also passed (11). The test-plan selector
chose the full lane. A separate draft starts ordinary hosted checks
on this candidate instead of a second broad local run.

## Result review

Agent technical review: independent architect GO for source and
focused evidence. Reviewed revision: base `332cd733`; plugin
`619500bf`, test `8e2583ec`, guide `4954b7cb`. Verification adequacy:
the mismatch regression covers the exact error, rejects the response
ID, and retains the checks for no attachment, ACK, or new prompt.
Whole-change validation is still outstanding. Keep the draft unmerged
until the hosted result and any findings are resolved.

## Operating plan

Use one question for a missed wake: **what is the last thing we can prove about this delivery, and what should the operator do?** Use the current delivery trace, not a new dashboard.

| Evidence | What to do |
|---|---|
| Pending; recipient is known busy or only supports next-turn pickup | Leave it queued for the supported turn. If it was supposed to wake an idle recipient, inspect the activation evidence for that same ID. |
| Claimed, or a native attempt is accepted or uncertain | Leave custody with its current owner. Do not issue a second claim or wake. |
| Delivered; no correlated reply or other evidence that work resumed | Report “ACK recorded; continuation unknown.” Check existing task output if a response was expected. Do not repeat the instruction. |
| Trace unavailable | Report “trace unavailable.” Use normal service-status guidance to distinguish a reachability problem from a delivery diagnosis. Preserve the ID privately; do not infer failure or success. |

During the next week of ordinary work, use existing task records to distinguish eligible deliveries that resumed unaided, needed a human prompt, or have unknown outcomes. Keep known-busy/passive deliveries out of the eligible denominator. If only incidents are visible, report incident counts, not a success rate. No new receipts, synthetic wakes, polling or scheduled report. The first useful result is one real incident explained without reading source or asking the user to reproduce it.

## What to simplify and what to leave alone

- **Claude:** Keep compact for orientation only. Removing registration and pickup there eliminated two side effects that had no guaranteed following turn. Native wake after natural idle compaction remains a separate observation.
- **OpenCode:** The older OC-1 report documents a saved message waiting seven minutes for a manual prompt with a previous wake still open. The later restored-authority error lacked an ID; the later lookup error had an ACK but no proof of continuation. These are not evidence of one cause. Trace the next occurrence before changing recovery. The proposed message change improves diagnosis, not delivery.
- **SQLite:** Main already contains the setup-to-BEGIN deadline guard (#434). It avoids unnecessary SQL; it does not explain why setup took so long. Do not add timeouts, retries or a storage migration on that evidence.
- **Windows:** Keep the descendant-cleanup problem in #377. An empty job count did not prove the known descendant had exited. Do not make restart the operator's default remedy for a missed delivery.
- **Coordination:** Put the conclusion in the existing incident once. Notify the human on a changed user-visible outcome, a blocker, or a decision. No new status bot or routine confirmation exchange.

**Stop rule:** If the trace answers the operator's question, stop. If separate incidents repeatedly stop at the same transition, reproduce that transition and look for an action to remove or an existing owner to reuse. Only broaden scope on that evidence.
