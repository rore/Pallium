# Disposable Hermes Windows qualification runner

<!-- agent-workflow:start -->
**Outcome:**
Qualify the Hermes integration through a manual disposable Windows runner without modifying the user's working environment.

**Target:**
One manual GitHub Actions workflow and its synthetic native qualification evidence.

**Scope:**
Add .github/workflows/hermes-native-qualification.yml through a separate runner-only PR, merge that runner after validation, then dispatch an immutable Pallium candidate for two pinned Hermes releases. Preserve the separate feature PR and shared reliability ownership.

**Constraints:**
No everyday applications, services, configuration, credentials, data, launchers, installed versions or persistent environment changes. No local dependency builds/native launches, paid inference, publishing, secrets, schedules or existing CI/protection changes. At most two manual native runs including one fix/rerun, two sequential release jobs per run, sixty minutes per job and four runner-hours total. Failed/skipped checks are not qualification. Previously disclosed local recovery remains unapproved and untouched.

**Completion criteria:**
A reviewed manual runner is merged separately, validates exact candidate/source/runtime identities, runs four required UI/memory cases per release without skipped acceptance cases and retains synthetic evidence. Native outcomes and limits are reported accurately, and all repository work is pushed.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Qualify the Hermes integration through a manual disposable Windows runner without modifying the user's working environment.","scope":"Add .github/workflows/hermes-native-qualification.yml through a separate runner-only PR, merge that runner after validation, then dispatch an immutable Pallium candidate for two pinned Hermes releases. Preserve the separate feature PR and shared reliability ownership.","constraints":"No everyday applications, services, configuration, credentials, data, launchers, installed versions or persistent environment changes. No local dependency builds/native launches, paid inference, publishing, secrets, schedules or existing CI/protection changes. At most two manual native runs including one fix/rerun, two sequential release jobs per run, sixty minutes per job and four runner-hours total. Failed/skipped checks are not qualification. Previously disclosed local recovery remains unapproved and untouched.","completion_criteria":"A reviewed manual runner is merged separately, validates exact candidate/source/runtime identities, runs four required UI/memory cases per release without skipped acceptance cases and retains synthetic evidence. Native outcomes and limits are reported accurately, and all repository work is pushed."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":["https://github.com/rore/Pallium/pull/328"]}

**Risk:** High

**Complexity:** Moderate

**Reason:**
Third-party lifecycle scripts and real Desktop startup require an OS boundary. A new manual CI runner executes pinned dependency builds and code from a validated immutable candidate. This is non-exempt CI work with explicit human approval and independent review.

**Discovery:**
Existing ci.yml has no native Hermes bootstrap/selection input; it must not be repurposed implicitly. Temporary HOME does not contain dependency/app writes. GitHub-hosted Windows is disposable; environment markers only guard accidental execution. The registered main workflow can accept a full candidate SHA and checkout/verify it without merging the feature. The reviewed proposal uses upstream lock-owned Python dependencies, public build scripts, task-local npm and a dedicated public UI journey.

**Material assumptions:**
The hosted Windows image can build and run the pinned public source: dependency/build/native failures disprove this; retain evidence and fix only supported runner/harness defects within the run cap. No hosted result proves Windows11/MSIX/updater behavior. No marker alone proves filesystem or network confinement; hosting supplies OS disposal, while runtime Python/terminal guards have explicitly narrower coverage than Chromium.

**Plan:**
Invoke Agent Workflow to create this Work Record and classify risk before the CI edit. Copy only the reviewed workflow proposal, remove proposal labeling, validate YAML and PowerShell syntax/argv plus identity/timeout/no-skip/artifact contracts. Run the whole-change selector and governance checks, obtain independent result review, push/open/attach the runner-only PR and merge after required checks/review. Dispatch on main with the exact candidate SHA. Retain run IDs/receipts and evidence before any fix/rerun. Stop at the approved execution cap or an actual human-only blocker; never work around isolation or weaken tests. Revert the one workflow through a PR if rollback is needed; no local rollback/environment action is authorized.

**Verification plan:**
Manual bounded isolation -> inspect trigger/permissions, hosted identity gate, strict runner-temp roots/reparse refusal, sequential matrix and timeout; parse every PowerShell script without executing it locally.
Immutable provenance -> validate full SHA input and exact checkout/source/runtime/bundle/executable checks before code execution and qualification; retain provenance.json.
Caller coverage -> require exact non-skipped TUI/Desktop x memory-off/on JUnit cases on both pinned releases, preserving public tool/session/lifecycle assertions.
Evidence retention -> always retain synthetic JUnit/native temp transcripts and hashes for seven days, including failed runs.
Repository correctness -> whole-change test selector, workflow/redline checks, independent result review and existing required CI; no application behavior is changed by the runner.

**Plan review:**
Agent technical review: /root/hermes_cd_plan_review independently reviewed the concrete proposal during the existing slice4 task, including full-SHA main-workflow checkout, native argv binding, candidate revalidation, isolation/evidence/no-skip limits. Findings were addressed before this implementation. Review is technical, not human authority. Staged result review follows.

**Approvals:**
Approved by user 2026-10-20: "Approved. And I told you this is a night job. Get this done"
This directly answers the presented proposal to add and merge the separate disposable Windows runner and dispatch it at most twice, capped at four runner-hours. It does not authorize local recovery or everyday rollout.

**Exceptions:**
—

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Created from current main bb239133a3ae86a37fe9f890beae87772b15f774 in a separate managed checkout and feat/hermes-native-qualification branch. Whole-change documentation exemption does not apply to the new workflow. Feature implementation remains on feat/hermes-production-slice4 / PR324. No native runs dispatched yet; approved run ledger starts at zero.

## Evidence

Agent technical review: /root/hermes_cd_plan_review, independent read-only staged result review, GO conditional on required CI. Reviewed revision:13a6030e. Verification adequacy: manual-only trigger, exact candidate revalidation, separate locked runtime stacks, native argv, source/binary hashes, mandatory non-skipped cases, provenance/retention and the recorded human scope were accepted. The reviewer explicitly notes that YAML bounds each run, while this task's ledger must enforce the total two-dispatch cap. Native qualification is not accepted by this review. Runner PR https://github.com/rore/Pallium/pull/328 is created and attached; zero native runs dispatched.

Safety contract test:1 passed in0.12s. All workflow PowerShell run blocks parsed without execution. Whole-change test selector requires the full lane; hosted full CI is pending. The real import boundary adapter produced0violations. Fresh redline verdict is GRAY; Agent Workflow is clean with0failed predicates. The first reporter attempt correctly stopped because the new checkout lacked the required boundary report; running the configured adapter resolved that prerequisite without any policy change. Staged independent result review is in progress. No local third-party dependency build or actual Hermes launch occurred.
