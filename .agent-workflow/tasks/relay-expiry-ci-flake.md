<!-- agent-workflow:start -->
**Outcome:**
Make the relay expiry reservation-validation E2E test deterministic without weakening production expiry validation.

**Target:**
`tests/test_relay_endpoint_repair_e2e.py` and its test setup.

**Scope:**
Adjust only the focused test timing/control needed for the expiry-during-reservation-validation scenario.

**Constraints:**
Do not change production expiry semantics or broaden the test beyond the reported CI flake.

**Completion criteria:**
The focused test passes reliably, affected test file passes, and workflow checks are clean.

**Risk:** Routine

**Complexity:** Simple

**Reason:**
Blue-zone test-only change with isolated blast radius.

**Approach:**
Trace the test and manifest validation callers, then make the test use a deterministic expiry boundary rather than wall-clock slack.

**Verification:**
Run the exact test node, the affected test file, and `scripts/agent-workflow-check.py`.

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Replaced the one-second sleep with a test-controlled clock that advances inside the reservation validator.
- Kept manifest expiry one hour ahead so manifest construction cannot race the wall clock; production code and expiry semantics are unchanged.
- `apply_patch` failed with machine-local Windows error 1327. Per `AGENTS.local.md`, the edit used a narrowly scoped deterministic PowerShell replacement limited to the two task files.

## Evidence

- `python -m pytest tests/test_relay_endpoint_repair_e2e.py -q -n 0`: 15 passed.
- `python -m pytest tests/ -x -q -n 0`: 4,948 passed, 34 skipped, 215 deselected, 2 xfailed.
- `git diff --check`: clean.
- `python scripts/agent-workflow-check.py --repo-root . --slug relay-expiry-ci-flake --redline-verdict build/redline-verdict.json`: no blockers; one non-blocking same-commit-order advisory.
- Independent Astra review rejected the initial future-`now` patch because it no longer proved post-validator sampling and retained a five-second race. The controlled-clock correction addresses both findings.

## Result review

The test now fails if production samples `current` before the reservation validator and passes only when expiry is observed afterward. No production files changed.
