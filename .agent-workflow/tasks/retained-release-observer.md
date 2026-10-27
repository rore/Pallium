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

**State:** Ready to implement
<!-- agent-workflow:end -->

Historical attribution stays uncertain: proving a real test defect does not prove it caused the earlier CI failure or other Relay incidents.
