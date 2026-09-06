<!-- agent-workflow:start -->
**Outcome:** The merged Linux service lifecycle change passes the Windows full-test CI job.

**Target:** Pallium repository.

**Scope:** Update the stale `_check_health` test double in `tests/test_service.py` only, plus this Work Record.

**Constraints:** Production code and service behavior remain unchanged; preserve all Unicode-home test coverage.

**Completion criteria:** The four Windows-only `test_install_carries_exact_home_in_unicode_launcher` cases pass with the timeout-aware health call.

**Risk:** Routine

**Complexity:** Simple

**Reason:** Test-only blue-zone change; one stale mock seam and no runtime surface change.

**Approach:** Mock the existing `_service_ready` seam because this launcher-path test does not exercise readiness diagnostics.

**Verification:** Run `TestStartWindows::test_install_carries_exact_home_in_unicode_launcher` on Windows, then the service test module and agent-workflow checker.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery: post-merge Windows CI failed because `_service_ready` now calls `_check_health(port, timeout=...)`, while this one Windows-only test still monkeypatches `_check_health` with a single positional parameter.
- Risk assessment: `tests/**` and `.agent-workflow/**` are blue zones; the referenced redline skill file is absent from this checkout, so classification used the checked-in redline policy directly.
- Plan self-review: changing the test double is sufficient; changing production code would weaken the explicit timeout behavior added by PR #120.

- Implementation correction: the first signature-only fix exposed that a health-only mock cannot satisfy the newer multi-endpoint readiness contract; moved the test double to the readiness boundary this launcher test actually depends on.

- Verification: the four formerly failing Windows parameter cases passed; the full service test module passed with 32 passed and 18 expected platform skips.
- Result review: final scope remains test-only and Routine/Simple. No production behavior changed.
- Skill feedback issue was not filed because external issue creation was not authorized; the report is preserved below.

## Evidence

- Failing CI: GitHub Actions run 34040349249, job 101505844008.
- Focused Windows regression: 4 passed in 0.55s.
- Complete service module: 32 passed, 18 skipped in 0.87s.
- Verification ran against the pending diff based on f2662666; the final commit SHA will be added after commit.

## Skill feedback (unsent)

**Trigger fired:** 5 — A skill cross-reference was broken.

**What the skill said (or failed to say):** assess-risk.md directs the agent to ../../agent-redline/SKILL.md, but that file is absent from the consumer checkout.

**What happened:** A routine test-only task could not follow the prescribed pre-edit redline-skill path. The checked-in redline policy and report script existed, but the referenced skill did not.

**Suggested fix:** Reference a bundled path that exists after bootstrap, or document the report-script fallback when the skill is unavailable.

**Work Record:** commit 9caf3836, .agent-workflow/tasks/codex-fix-linux-service-ci.md in rore/Pallium.