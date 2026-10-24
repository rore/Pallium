# Cooperative Windows service lifecycle — behavior review and implementation plan

<!-- agent-workflow:start -->
**Outcome:**
Produce one source-grounded implementation plan and behavior-review contract for cooperative Windows service lifecycle recovery, ready for separate technical and human behavior review.

**Target:**
Pallium Windows service lifecycle at published origin/main fd14a77d19713e878105a537de0dfee9735dc88e.

**Scope:**
Planning artifact only in this Work Record: inspect selected-base supervisor, child stop callbacks, launcher generators, restart wrapper and existing test harnesses; define containment, stop, settlement and bounded restoration behavior plus mocked regression coverage.

**Constraints:**
No product code, tests, live service actions or census, installed configuration changes, forced maintenance, push or PR. Preserve shared main and all existing owners' branches. Do not transplant installed callbacks into the selected source. No network, registry, daemon, backup or new orchestrator mechanism.

**Completion criteria:**
Record the exact isolated base and source findings, reconcile launcher-generator differences, specify minimum touched files and an implementation sequence, resolve spawn fencing/settlement/restoration review corrections, list mocked regression cases and remaining behavior decisions, and leave State returned to planning awaiting behavior review.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Produce one source-grounded implementation plan and behavior-review contract for cooperative Windows service lifecycle recovery, ready for separate technical and human behavior review.","scope":"Planning artifact only in this Work Record: inspect selected-base supervisor, child stop callbacks, launcher generators, restart wrapper and existing test harnesses; define containment, stop, settlement and bounded restoration behavior plus mocked regression coverage.","constraints":"No product code, tests, live service actions or census, installed configuration changes, forced maintenance, push or PR. Preserve shared main and all existing owners' branches. Do not transplant installed callbacks into the selected source. No network, registry, daemon, backup or new orchestrator mechanism.","completion_criteria":"Record the exact isolated base and source findings, reconcile launcher-generator differences, specify minimum touched files and an implementation sequence, resolve spawn fencing/settlement/restoration review corrections, list mocked regression cases and remaining behavior decisions, and leave State returned to planning awaiting behavior review."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** High

**Complexity:** Moderate

**Reason:**
Actual artifact is blue workflow metadata but non-exempt. Proposed lifecycle changes cross process ownership, crash policy and persistence-sensitive shutdown; judgment raises risk to High. Several cooperating components and Windows OS assumptions require expanded planning.

**Discovery:**
Pending narrowly scoped selected-base source inspection. Local origin/main equals requested published base; isolated checkout is clean and not ahead at initialization.

**Material assumptions:**
Planning approval covers analysis and this record only; any implementation or installed change needs its own exact authorization. If source lacks the assumed cooperative callbacks or a safe containment mechanism, revise the plan and keep implementation blocked.

**Plan:**
First implementation step: invoke the /agent-workflow skill to create or resume the Work Record and classify risk before any code edit. This task ends after source-grounded planning and review handoff; product implementation is excluded.

**Verification plan:**
Read source and existing harnesses; inspect artifact diff and run governance-only validation if available. Do not execute application tests or live observations. Future implementation validation will be specified after discovery.

**Plan review:**
Pending clean-context technical review and separate human behavior review. No implementation approval is implied by this planning assignment.

**Approvals:**
Planning-only scope accepted by parent assignment. Human implementation/behavior approval has not been supplied; do not fabricate an approval quote.

**Exceptions:**
—

**State:** Blocked or returned to planning
<!-- agent-workflow:end -->

## Implementation

- Initialized expanded record before source discovery on isolated branch `feat/cooperative-windows-service-plan` in `C:/Dev/rore/Pallium/build/cooperative-windows-service-plan`; sole source base `fd14a77d19713e878105a537de0dfee9735dc88e`. Shared checkout is dirty and was left untouched.
- Applicability: intended path `.agent-workflow/tasks/cooperative-windows-service-plan.md` is a Work Record, expressly ineligible for documentation-only exemption; normal workflow applies. No roadmap state change is assigned.

## Evidence

- Local `refs/remotes/origin/main` and `git merge-base HEAD origin/main` both equal selected base. No fetch performed.
- No application tests, service calls, process census or installed-file reads performed.

## Result review

Pending artifact completion and parent review. This worktree remains owned by the planning task for review and revision; do not retire it while that use remains.
