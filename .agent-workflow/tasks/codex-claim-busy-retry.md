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

**Verification plan:** Exact snapshot SHA256 and three-file diff; existing 84 focused and 441 distinct affected case evidence; real HTTP lifecycle controls against current main; whole-change scripts/test-plan.py selection and one required full non-slow run; import/workflow checks; independent result review and fresh platform CI; public-content privacy inspection.

**Plan review:** Pending independent publication_review destination/scope assessment before source integration.

**Approvals:** User's standing separate-developer publication directive authorizes normal isolated implementation, review, push and merge once gates pass. Manager explicitly directed this stable snapshot's separate follow-up publication; no further routine scope permission is pending. No live environment change is authorized here.

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

An isolated worktree was created from current main. No source files have been copied yet. Plan/destination review is pending. PR #381 remains separately held at e7ee020bfd2a6fa9fbc207d3190887cee1cc64eb with failed platform CI. The private observation-workflow option is unexecuted and superseded by the next-required-run disposition.

## Saved evidence

The immutable captured source identities are Codex helper SHA256 `4a531a56fae99f3cfd48175e0e1a71f687460c25d4666b712a91a3e0ce90c83b`, Claude parity helper `acb52e5c93c0d70f8ec67878ca7641422624af8f603ab0d7dfd7ecd7f71cd8ac`, and tests `8b6606e0e6d65c411052e487b4c2a2beaa63b775d6086b9ac1528c16454cf553`. Earlier focused evidence passed 84 cases. The affected run passed 439 of 441 with two WinError 206 fixture failures; the exact same two cases passed in a saved short-path control. This is disjoint evidence over 441 cases, not a single clean affected run. No destination or platform qualification is inferred solely from source identity.
