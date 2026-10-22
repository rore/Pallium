# Hermes missing-route reproduction and regression coverage

User request: "ok, let's reproduce this in isolation and add the missing regression coverage for both injection paths. Keep my working environment untouched, use resources wisely, and push the work."

<!-- agent-workflow:start -->
**Outcome:** Reproduce the reported Hermes missing-route failure in isolation and cover both TUI-owned and gateway-backed Pallium injection with observable regression evidence.

**Target:** Pallium's Hermes test and qualification surfaces.

**Scope:** tests/test_hermes_relay_plugin.py; tests/test_hermes_route_recovery_e2e.py; tests/fixtures/hermes_route_probe.py; docs/designs/hermes-native-qualification.md; this Work Record. Inspect immutable Hermes source and existing isolated qualification assets. Canonical roadmap remains manager-owned.

**Constraints:** Test/proof and contributor documentation only; no runtime, dependencies, CI, policy or protected-contract edits. No automatic resend, restart or routing-store repair. Keep everyday applications, services, installations, profiles, credentials, data, PATH, updaters, existing distros/defaults and the primary dirty checkout untouched. No normal-account Hermes import/launch, global dependency install, paid inference or duplicate qualification. Use the existing task-owned protected offline WSL namespace if actual Hermes execution is required; retain provenance and failed evidence. Do not count stubs/helper checks as full host/UI qualification.

**Completion criteria:** A pinned actual-upstream reproduction establishes the missing-route outcome and distinguishes it from TUI-owned injection. Regressions drive the production Pallium plugin/caller surfaces and assert public Relay state, exact-session identity, no premature ACK and no unsafe duplicate wake for both injection paths, with healthy/control and failure evidence. Contributor guidance describes actual coverage and remaining upstream risk. Focused and selected validation plus clean independent review are evaluated, and the coherent work is pushed with a reviewable PR.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Reproduce the reported Hermes missing-route failure in isolation and cover both TUI-owned and gateway-backed Pallium injection with observable regression evidence.","scope":"tests/test_hermes_relay_plugin.py; tests/test_hermes_route_recovery_e2e.py; tests/fixtures/hermes_route_probe.py; docs/designs/hermes-native-qualification.md; this Work Record. Inspect immutable Hermes source and existing isolated qualification assets. Canonical roadmap remains manager-owned.","constraints":"Test/proof and contributor documentation only; no runtime, dependencies, CI, policy or protected-contract edits. No automatic resend, restart or routing-store repair. Keep everyday applications, services, installations, profiles, credentials, data, PATH, updaters, existing distros/defaults and the primary dirty checkout untouched. No normal-account Hermes import/launch, global dependency install, paid inference or duplicate qualification. Use the existing task-owned protected offline WSL namespace if actual Hermes execution is required; retain provenance and failed evidence. Do not count stubs/helper checks as full host/UI qualification.","completion_criteria":"A pinned actual-upstream reproduction establishes the missing-route outcome and distinguishes it from TUI-owned injection. Regressions drive the production Pallium plugin/caller surfaces and assert public Relay state, exact-session identity, no premature ACK and no unsafe duplicate wake for both injection paths, with healthy/control and failure evidence. Contributor guidance describes actual coverage and remaining upstream risk. Focused and selected validation plus clean independent review are evaluated, and the coherent work is pushed with a reviewable PR."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-hermes-agent-integration"}],"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Intended paths are BLUE; judgment raises risk for cross-runtime routing proof, ambiguous delivery fencing and source-authenticity/isolation. No production or protected behavior change.

**Discovery:** Fresh clean main1de7f0174173588ff708dc3cee90872159df03d6 in a new managed checkout on feat/hermes-missing-route-regressions. Whole-change documentation exemption is unavailable for test paths; deterministic Redline BLUE. Upstream issue142844 describes live local session plus absent scoped route causing queued admissions to pause with admission_conflict. Current inspected upstream81a55437f3f31a9f12a30c53b6c5d49d420898aa still has the guard. Pallium's production plugin blob3bda437ca8c213f6d7aa8eff30f50cac945f3ab6 fences before ctx.inject_message and claims/ACKs only later. Hermes routing tries TUI ownership first, then gateway; gateway scheduling can succeed before dispatch refuses a missing route, which need not emit the same admission_conflict signature. Existing real gateway/TUI tests do not inject the missing-route fault. Existing task WSL distro and protected namespace are retained; prior matrix evidence does not cover this new fault or release0.22.4.

**Material assumptions:** Actual pinned source can be exercised through existing isolated runtimes without installing or launching against user state. If prerequisites require unsafe host changes, choose a smaller contained actual-source probe or report the exact limitation; never silently substitute a mock for claimed real-upstream proof. Host route selection is version/topology-specific; distinguish live-restore refusal from scheduling/dispatch refusal and preserve observed outcomes rather than forcing an expected signature. A genuine production safety defect returns to planning for any runtime correction.

**Plan:** Invoke Agent Workflow, evaluate applicability and create/classify this Work Record before test edits; obtain clean-context independent plan review. Inspect exact released/current-upstream injection and local-recovery prerequisites with a cheap bounded investigator. Reuse existing Pallium plugin/HTTP fixtures for deterministic two-path regression oracles; add only the smallest actual-source probe needed to reproduce real missing-route behavior in the protected offline namespace. Cover healthy routing, missing route, busy/queued progress boundaries, exact identity and unchanged pending/unclaimed public state without retrying uncertain native actions. Preserve immutable source hashes, diagnostic stage and normal cleanup; use synthetic anonymous local data and no provider calls. Run focused nodes before the affected subsystem, select configured whole-change validation once, update contributor coverage, obtain clean result review, push a coherent checkpoint and create a PR. No new full UI matrix, generic reliability takeover or upstream patch submission.

**Verification plan:**
- Actual missing-route failure and path distinction -> pinned real-Hermes source execution in the existing isolated namespace, retained source/runtime hashes and explicit reached/unreached outcomes; do not count this as UI qualification.
- Pallium observable safety on both paths -> production-plugin caller/HTTP regressions with exact returned IDs, public delivery reads, healthy and missing-route controls, zero premature receiver attempts/ACK, repeated poll/no duplicate injection and Unicode payload isolation.
- Minimal correct coverage and documentation -> independent plan/result review, exact focused pytest nodes then affected subsystem, source-checked contributor statements and Markdown links.
- Safe durable delivery -> unchanged source/isolation/cleanup postconditions, Redline/workflow and whole-change selector, single configured hosted lane, retained failures and pushed exact head/PR relationship; no installed rollout or unrequested merge.

**Plan review:** Agent technical review: /root/hermes_route_review, clean-context nonimplementer, GO before implementation. Require separate pinned actual-source routing proof because the existing Context fixture stubs injection; retain stage-specific refusal outcomes and distinguish route probes from whole-host/UI qualification.

**Approvals:** Direct user authorization covers isolated reproduction, regression tests, review and push. No installed rollout, production correction, upstream submission or automatic recovery is authorized by this test task.

**Exceptions:** —

**State:** Ready to implement
<!-- agent-workflow:end -->

## Implementation

Workflow invoked before test changes. Whole-change applicability requires a Work Record; BLUE floor raised to Elevated by judgment. Manager informed of the exact bounded assignment and no runtime/reliability overlap. Existing exact feature participation was read back and reused; no duplicate attachment or roadmap edit.

Independent plan GO received. Proceed with caller regressions plus pinned real-source proof; source investigator is read-only and parent owns namespace execution. No new host or bootstrap has been started.

## Evidence

Initial intended-path applicability and Redline reports are retained in build/. Actual reproduction, test runs and source/runtime receipts are pending. Historical production qualification remains unchanged in PR324 and its records.

## Result review

Pending implementation and verification. Worktree retained for this active assignment; everyday environment is untouched.
