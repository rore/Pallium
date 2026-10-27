# Retained release observation

<!-- agent-workflow:start -->
**Outcome:** Establish whether the retained-wake release completion test can miss a committed release, then correct only a demonstrated observer defect.

**Target:** The production-lifespan retained-wake test and its native release/delivery assertions.

**Scope:** tests/test_codex_retained_wake.py and this Work Record, on current main4b5e5d06. No old PR reopening.

**Constraints:** Preserve native deadlines, the five-second observation bound, typed-refusal, pending/fence/no-owner and exactly-once delivery/ACK assertions. No production, protected-contract, helper/framework, provider or installed changes. No unchanged replay or full-suite campaign.

**Completion criteria:** One deterministic worker-after-callback ordering shows whether native release commits while the old observer remains unset. A demonstrated observer correction passes that ordering plus existing lifecycle variants and relevant unchanged controls. Preserve the historical failure and uncertainty about its cause.

**Requirement baseline:**
{"source":"manager app adoption of user root-cause plan, 2026-10-27","outcome":"Establish whether the retained-wake release completion test can miss a committed release, then correct only a demonstrated observer defect.","scope":"tests/test_codex_retained_wake.py and this Work Record, on current main4b5e5d06. No old PR reopening.","constraints":"Preserve native deadlines, the five-second observation bound, typed-refusal, pending/fence/no-owner and exactly-once delivery/ACK assertions. No production, protected-contract, helper/framework, provider or installed changes. No unchanged replay or full-suite campaign.","completion_criteria":"One deterministic worker-after-callback ordering shows whether native release commits while the old observer remains unset. A demonstrated observer correction passes that ordering plus existing lifecycle variants and relevant unchanged controls. Preserve the historical failure and uncertainty about its cause."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** BLUE test/record paths; asynchronous lifecycle observation needs independent review to preserve the recovery contract. No production or persisted behavior changes.

**Discovery:** The target function is AST-identical on main and failed355a. A native wake worker commits release asynchronously. The observer checks released only in callback finally, then later skips that finally once released is set; worker completion after the callback can strand only the test event. Retained CI40446458108 does not record the decisive ordering.

**Material assumptions:** Suspected observer race must be shown with a successful native transition and fresh durable reservation read, not synthetic flags alone. If not established by the one focused ordering, stop with the missing A/B observation; no escalating probes.

**Plan:** Invoke Agent Workflow and classify before edits; record this plan first. Add a local forced-order variant to the existing journey using its barriers and real DB. Preserve the original completion assertion for RED. If durable release succeeds and that assertion fails, await the actual worker release witness and existing worker settlement instead of the racy callback event. Run that case and existing fault variants plus only relevant native controls, then independent actual source/result review.

**Verification plan:** Causal mechanism -> one forced worker-after-callback case, native release result and fresh reservations read, unchanged five-second assertion. Preserved contract -> all existing production-lifespan variants and native release/rollback controls. Governance -> existing selector, Redline and Work Record checks. No full suite or hosted campaign in this bounded assignment.

**Plan review:** Agent technical review: @pallium-manager, authorized app message adopting the finite plan and deterministic native-DB ordering; coordinator independently confirms execution of that same check. No additional ownership or approval gate is pending.

**Approvals:** Not required at this risk level; existing user bug-fix authority and manager adoption apply.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

Historical attribution stays uncertain: proving a real test defect does not prove it caused the earlier CI failure or other Relay incidents.

## Causal reproduction

At ece0044dfb7fdd3a8b4916ced89f917afedd12b9, the one forced worker-after-callback case failed at the original release_sweep_completed.wait(5) assertion in8.45s. The preceding controlled ordering, successful native release result and fresh registry.reservations() read all passed: the old reservation was absent while the completion event remained unset. The two intentional refusal warnings were retained; no unrelated failure or cleanup error occurred. This demonstrates the observer race without establishing the original CI ordering. Raw log, JUnit and exact command/source hash are in build/retained-release-observer/red.* and red-command.json/red-result.json.

The correction removes only the callback-dependent completion event and waits on the existing successful-release witness, with the same five-second bound and existing worker joins. Native deadlines, release count, fence/pending/no-owner, actual hook payload/ACK and backlog assertions remain unchanged. No production correction or further A/B probe is justified by this demonstrated test defect.

## Focused result

At2547ccf33bdc4ba218d28ddf6c1a5333e44f9774 the forced ordering passes1/1 in1.85s; the three original production-lifespan fault variants plus two unchanged native release controls pass5/5 in4.82s. No failures/errors/skips in those reports. First control selection used the wrong test file, exited4 and executed zero tests; its receipt remains separate from the corrected selection. Same supported isolated interpreter and private environment, no clock/budget/product changes. The finite discriminating check is complete; no stacks or further A/B probes, full suite or hosted run were needed. Existing source/result review remains the final bounded gate; full release qualification is not claimed.

## Result review

Agent technical review: @astra-reviewer turn01a17c30-13cc-7c80-a100-e4fdb42cd57a, actual narrow SOURCE/RESULT GO, independently inspected the base-to-source and RED-to-correction diffs, successful release producer, exact source hash and all three native XML receipts.

Reviewed revision: 2547ccf33bdc4ba218d28ddf6c1a5333e44f9774; test SHA256d5592e505918fc9d314c767d67549026a59f4b95eb74ab54cd49d4be1a72b3b1; later record-only commits preserve it.

Verification adequacy: sufficient for the demonstrated test-observer correction: committed release and fresh absent old fence precede the failing old observer, corrected forced order passes with unchanged5s bound, and all five selected lifecycle/native controls pass. Only the incorrect observer assertion of74 original assertions changed; unrelated module nodes are identical. No extra reviewer run or chain, full/hosted campaign, production reliability claim, historical CI attribution or live action follows. Normal release qualification remains separate from this finite diagnostic assignment.

## PR review remediation

Published PR #365 at83c2cb41e6c6a37a001cf37bb0b9f69da9a7ff3d. Normal required CI40466346732 passed both Linux full lanes and Windows smoke; hosted governance40466346595 passed. This is release qualification, separate from the finite diagnostic check above.

CodeRabbit identified two minor gaps in the added regression's proof: the barrier signaled after exceptional callback exit, and registry.reservations() can mask a failed refresh as empty. Require normal callback return before signaling; read the native codex_wake_snapshot directly and assert initialized authority plus absence at both new proof sites. No observer correction, deadline, existing lifecycle assertion or production behavior changes.

The six affected lifecycle cases pass6/6 in7.08s in the same supported private environment, source SHA256e784bd9d4157c5a5cb74f238b665b3ed51a4027f101dd2a13e661a14474859b4. Original receipts remain separate. Existing independent review covers the causal correction; the small stricter-proof delta will be reviewed by that same reviewer before merge. New-head required CI remains mandatory, with no optional campaign or duplicate full local run.
