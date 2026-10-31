# Retry a definitively unadmitted exact Codex claim once

<!-- agent-workflow:start -->
**Outcome:** An exact Codex hook claim can recover from one explicit pre-admission busy rejection within its original finite budget, without replaying uncertain requests.

**Target:** Shared Codex and Claude hook HTTP request helpers.

**Scope:** integrations/codex/hooks/common.py, integrations/claude-code/hooks/common.py, tests/test_codex_claim_busy_retry.py and this Work Record. Publish the already captured stable three-file snapshot independently of PR #381 when supported by source and validation.

**Constraints:** Preserve request bytes, claim expiry, original absolute hook deadline, two-second request budget, all existing assertions and no-replay rules. No new dependencies, workflow edits, standalone diagnostic campaigns, live installation, service actions or incident-owner checkout/index changes. Do not claim this fixes PR #381's three Linux failures.

**Completion criteria:** Retry at most once only for a complete bounded typed 503 relay_busy/retryable response with one Retry-After: 1 header. Reject ambiguity, redirects, malformed/duplicate response data, invalid identity/expiry and exhausted budgets. E2E coverage proves real HTTP claim recovery, one emission/ACK and post-admission no replay. Required validation, independent review and current-head checks precede merge.

**Requirement baseline:**
{"source":"authorized-stable-busy-retry-publication","outcome":"An exact Codex hook claim can recover from one explicit pre-admission busy rejection within its original finite budget, without replaying uncertain requests.","scope":"integrations/codex/hooks/common.py, integrations/claude-code/hooks/common.py, tests/test_codex_claim_busy_retry.py and this Work Record. Publish the already captured stable three-file snapshot independently of PR #381 when supported by source and validation.","constraints":"Preserve request bytes, claim expiry, original absolute hook deadline, two-second request budget, all existing assertions and no-replay rules. No new dependencies, workflow edits, standalone diagnostic campaigns, live installation, service actions or incident-owner checkout/index changes. Do not claim this fixes PR #381's three Linux failures.","completion_criteria":"Retry at most once only for a complete bounded typed 503 relay_busy/retryable response with one Retry-After: 1 header. Reject ambiguity, redirects, malformed/duplicate response data, invalid identity/expiry and exhausted budgets. E2E coverage proves real HTTP claim recovery, one emission/ACK and post-admission no replay. Required validation, independent review and current-head checks precede merge."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":["https://github.com/rore/Pallium/pull/381"]}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Hook request replay is sensitive to admission uncertainty and deadline exhaustion. No API, schema, workflow or protected test contract changes. The exact snapshot is already independently reviewed; verify destination compatibility rather than alter it speculatively.

**Discovery:** Base origin/main is 9d01176483d7a353d1f88de7830a31e409c5959b. The two existing helpers match the snapshot before its isolated retry hunk. Existing HTTP routes provide typed pre-admission busy responses and contain post-admission callback/projection failures; PR #381's pool reassignment is not assumed necessary. All relay_request callers in both hook trees were inspected. Captured evidence covers 84 focused and 441 affected cases, preserving the original two Windows path-length failures and the same two short-path passes.

**Material assumptions:** Existing main exposes the same exact-claim and busy-response contracts used by the snapshot's E2E test. Verify this at the actual destination. Source hashes must match the immutable captured snapshot. If tests or source demonstrate a PR #381 dependency, stop and state it explicitly.

**Plan:** Invoke Agent Workflow before source edits and retain this record for this separate follow-up PR. Obtain independent plan/destination review of the exact snapshot. Copy only its three hash-verified files. Reuse exact unchanged focused/affected evidence and reviews within their recorded limits; run the destination selector, required full non-slow suite once, import boundaries and workflow checks in the existing isolated runtime. Preserve failures. Review destination E2E coverage and any public disclosure before pushing a new branch and opening the follow-up PR. Use existing required platform jobs without CI configuration changes. Merge only when required checks and inline findings are settled. No standalone observation run; any proposed target observation must be reviewed, bounded, test-only and genuinely compatible with existing CI before inclusion.

**Verification plan:**
- Immutable correction -> compare all three snapshot SHA256 values and destination diff.
- Prior evidence limits -> primary XML/manifests for 84 focused cases and 441 owner cases, distinguishing 424 destination-compatible identities from 17 source-only compact cases and preserving both failed path cases.
- Real destination HTTP lifecycle and regressions -> selected full non-slow suite once, including the new claim-recovery/post-admission controls and unchanged actual-hook tests.
- Structural and workflow obligations -> import boundaries, Redline classification and local Agent Workflow checker.
- Publication acceptance -> independent result review, fresh current-head platform CI and disposition of every inline finding.
- Public privacy -> inspect every added diff line and PR prose for private identifiers, local paths or operational pointers.

**Plan review:** Agent technical review: independent publication_review returned PLAN GO at e6c5aec3 on main 9d011764. Both helper diffs contain only the same bounded retry hunk; all three snapshot hashes match. Existing main already provides typed pre-admission 503, exact claim atomicity and post-admission exception containment; no PR #381 dependency was found. Elevated/Moderate is appropriate. Reuse exact focused evidence within its limits; require destination full validation and normal platform CI. The new HTTP E2E proves claim recovery, a single claimed attempt, formatting one delivery and acknowledged read state; it does not directly observe native hook emission or count wire ACKs. Existing unchanged hook coverage supplies that separate contract evidence.

**Approvals:** User's standing separate-developer publication directive authorizes normal isolated implementation, review, push and merge once gates pass. Manager explicitly directed this stable snapshot's separate follow-up publication; no further routine scope permission is pending. No live environment change is authorized here.

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

An isolated worktree was created from current main. Independent plan/destination review is GO before source integration. PR #381 remains separately held at e7ee020bfd2a6fa9fbc207d3190887cee1cc64eb with failed platform CI. The private observation-workflow option is unexecuted and superseded by the next-required-run disposition.

## Saved evidence

Implementation: copied exactly the three immutable files after independent plan approval; each destination SHA256 matches the captured snapshot. No probe or workflow delta is included. One destination full non-slow run is next; source/config hashes will be compared before and after. Earlier focused evidence is reused without rerunning its controls.

Independent source review is GO at 6aeff7c8. The whole-change selector requires the full lane. Its single full attempt stopped with 1,546 passes, two skips and two failures in 195.64 seconds; all 84 new busy-retry cases passed normally, including both real HTTP lifecycle cases. All recorded source/config hashes remained unchanged. This is incomplete failed full-suite evidence, not complete destination qualification. Import boundaries pass; Redline is GRAY with unchanged API. The initial workflow check was advisory only for verification-method formatting; the mappings above correct that record format.

Both failures occurred in unchanged actual-hook tests before the new retry implementation: the protected busy-queue recovery contract and the no-hook completion recovery test. Both replace relay_request with their own test adapter. The validation driver placed temporary fixtures beneath an enclosing Git checkout; real scope resolution is allowed to recognize that project and switch away from the pinned fixture scope. A single cached-failure command, `python -m pytest --lf --lfnf=none -q -n 0`, then ran the same two cases with temporary fixtures outside every Git ancestor. Both passed in 3.78 seconds with unchanged source/config hashes and assertions. The original failed full run remains preserved. No duplicate full, remainder campaign, timeout change or protected-test edit was made. Fresh normal platform CI must establish complete current-head qualification before merge.

## Result review

Agent technical review: independent publication_review returned SOURCE GO and LIMITED PUBLICATION GO for a held separate PR and normal required CI. Full qualification remains NO-GO.

Reviewed revision: `6aeff7c802a522d93719dc87349edc10ec7665e2`.

Verification adequacy: the reviewer independently parsed the raw full and two-case control XML, verified all 84 new tests passed, inspected both test adapters and scope-resolution branches, and matched all 976 current code/config hashes to the unchanged full-run manifest. The protected failure explicitly shows recognized repository scope replacing fixture scope; the second failure is consistent with the resulting wrong-scope wake guard. The two exact failures passed outside Git ancestry, but this supplies no missing full-suite coverage. The control manifest records a source-unchanged assertion and references the existing digest set through its driver; it does not contain a separate raw digest map. Preserve failed full evidence and State Blocked while normal current-head platform CI establishes the remaining coverage. No merge or installed acceptance is asserted. Record-only publication bookkeeping preserves this source identity.

The immutable captured source identities are Codex helper SHA256 `4a531a56fae99f3cfd48175e0e1a71f687460c25d4666b712a91a3e0ce90c83b`, Claude parity helper `acb52e5c93c0d70f8ec67878ca7641422624af8f603ab0d7dfd7ecd7f71cd8ac`, and tests `8b6606e0e6d65c411052e487b4c2a2beaa63b775d6086b9ac1528c16454cf553`. Earlier focused evidence passed 84 cases at those helper/test identities; its real HTTP cases used the owner backend, which was not hashed in those manifests, so destination E2E qualification remains separate. The owner's affected run passed 439 of 441 with two WinError 206 fixture failures; the same two cases passed in a saved short-path control. The 234 parity cases match the destination test file. The agent-hook file includes compact additions absent from this destination, so its cases are source evidence rather than exact destination coverage. The 441-case total is disjoint owner evidence, not a single clean run or a complete destination claim. No destination or platform qualification is inferred solely from source identity.
