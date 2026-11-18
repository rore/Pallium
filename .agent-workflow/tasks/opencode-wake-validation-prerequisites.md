# Restore validation prerequisites for the reviewed wake-context fix

<!-- agent-workflow:start -->
**Outcome:** Required governance validation runs with an adapter-compatible import-linter and continues to enforce real boundary and workflow evidence.

**Target:** Validation prerequisites for the unchanged OpenCode V2 candidate in PR #417 at `80f7208e10eadf3a62859e43c4c019f7880b66ea`.

**Scope:** Restore the CI validation-tool prerequisite and add a regression contract for the installed version, leaving reviewed application behavior unchanged.

**Constraints:** Do not change maintained reporters or skills, policy, permissions, triggers, gate enforcement, the lock, reviewed application/test/README files or dashboard oracles. Preserve failed validation evidence. Do not skip checks, fabricate verdicts or weaken the original feature's safeguards.

**Completion criteria:** CI installs the adapter-compatible version already in the lock. The regression rejects unpinned, wrong or duplicate requirements. Real boundary reporting, Redline and Agent Workflow complete without bypasses. Reviewed application file identities remain unchanged, and hosted results and remaining application failures are reported separately.

**Requirement baseline:**
{"source":"Coordinator-assigned validation prerequisite for PR #417; original feature requirements remain in .agent-workflow/tasks/opencode-wake-context-continuity.md","outcome":"Required governance validation runs with an adapter-compatible import-linter and continues to enforce real boundary and workflow evidence.","scope":"Restore the CI validation-tool prerequisite and add a regression contract for the installed version, leaving reviewed application behavior unchanged.","constraints":"Do not change maintained reporters or skills, policy, permissions, triggers, gate enforcement, the lock, reviewed application/test/README files or dashboard oracles. Preserve failed validation evidence. Do not skip checks, fabricate verdicts or weaken the original feature's safeguards.","completion_criteria":"CI installs the adapter-compatible version already in the lock. The regression rejects unpinned, wrong or duplicate requirements. Real boundary reporting, Redline and Agent Workflow complete without bypasses. Reviewed application file identities remain unchanged, and hosted results and remaining application failures are reported separately."}

**Relationships:**
{"schema_version":1,"sources":[{"provider":"minimap","scope_ref":"roadmap:v1:git:github.com/rore/pallium#roadmap","local_ref":"item:v1:add-wake-first-relay-delivery"}],"pull_requests":["https://github.com/rore/Pallium/pull/417"]}

**Risk:** Elevated

**Complexity:** Simple

**Reason:** The self-protected governance workflow is RED and requires architecture-review. This changes only its validation-tool prerequisite to an already locked version. No permissions, triggers, enforcement, security, persistence or caller behavior changes are proposed.

**Discovery:** Hosted governance installed import-linter 2.17 through an unconstrained install. The unchanged adapter calls a private helper absent in that version. The lock and successful local real-report evidence use 2.15. A failed report prevents Redline evidence and blocks Agent Workflow; a dependency pin must restore the real report, not bypass either gate.

**Material assumptions:** The existing locked 2.15 dependency still supports the unchanged adapter. Successful local report evidence supports this; hosted execution must confirm it after a separately released update. Pinning the prerequisite cannot qualify the separate dashboard failure or imply product recovery.

**Plan:** Invoke the /agent-workflow skill to create the Work Record and classify risk, before any code edit. Done. The exact pin and contract are implemented, checked and accepted by independent scoped result review. Publish unchanged reviewed CI/test bytes and sanitized records in one normal commit above the original candidate. Verify the published head and blobs before applying the authorized existing architecture label. Observe existing hosted runs without retries and retain earlier failures.

**Verification plan:** Locked validation prerequisite → one proposed caller-contract test parses the real workflow install step and uv.lock and requires the explicit locked version. Real boundary reporting and fail-closed behavior → reuse the successful 2.15 adapter report and existing checker/Redline/aggregate controls; require fresh hosted governance after a released update. Feature safety → preserve the four reviewed file identities and reuse accepted source/feature evidence. Delivery honesty → retain the failed 3.13 dashboard result, opposite-lane passes and all earlier failures.

**Plan review:** Agent technical review: independent scoped architecture/plan/verification-adequacy GO at base `80f7208e10eadf3a62859e43c4c019f7880b66ea`. No blocking finding or scope expansion. Collect all import-linter requirement tokens before equality/count checks and reject a missing real install step or non-unique lock entry. This is technical plan acceptance, not an authenticated repository label or push authority. The accepted V2 review is reused.

**Approvals:** Coordinator accepts actual scoped architecture/source/verification-adequacy GO and releases one normal commit, a fast-forward update to PR #417, approved record/body updates and association of the existing `architecture-reviewed` label only after exact published-head verification. This technical checkpoint action is not CODEOWNER approval or a gate waiver. Normal synchronize/labeled events and bounded native CI observation are permitted. No new local tests, application/full campaign, maintained-content/policy/lock/dashboard/reviewed-file edit, dependency installation, manual CI retry, new agent, live operation, cleanup, merge or installation.

**State:** Blocked
<!-- agent-workflow:end -->

## Ownership and boundaries

Branch: `fix/opencode-wake-validation-prerequisites`.
Base: `80f7208e10eadf3a62859e43c4c019f7880b66ea`.
Related delivery: [draft PR #417](https://github.com/rore/Pallium/pull/417).
Feature: [Add wake-first Relay delivery](../../roadmap/features/add-wake-first-relay-delivery.md).
Original implementation record: [wake context continuity](opencode-wake-context-continuity.md).

This record owns only the validation prerequisite. The original feature's exact
requirement baseline stays unchanged in its implementation record. Preserve that
record, publication metadata and private evidence; this is not a replacement
feature implementation record.

Implementation paths under the current release:
1. `.github/workflows/agent-workflow.yml`
2. `tests/test_agent_workflow_ci.py`
3. This owning record.

No maintained adapter/reporter/skill, policy, lock, application module, wake test,
README, dashboard fixture/oracle or CI routing/enforcement change is in scope.

## Reviewed minimum delta

Change only the redline job's install command:

```diff
-      - run: pip install -e "." pyyaml jsonschema import-linter
+      - run: pip install -e "." pyyaml jsonschema import-linter==2.15
```

One test is implemented as
`test_redline_installs_locked_import_linter`, to the existing
`tests/test_agent_workflow_ci.py` caller-contract file.
Use installed PyYAML to parse the actual workflow's `jobs.redline.steps`.
Use stdlib `tomllib` to read the unique `import-linter` entry from `uv.lock`.
Use stdlib `shlex` to parse the actual pip-install step.
Require exactly one matching requirement and assert it equals
`import-linter==<locked version>`.
An unpinned, differently pinned or duplicate requirement must fail this one
assertion path. Do not execute pip or create a new test harness.

The unconstrained workflow failed the new contract at its version assertion.
After the one-line pin, the unchanged test passed. Both outcomes are retained.

## Evidence and proposed later checks

Hosted [governance run](https://github.com/rore/Pallium/actions/runs/44303988832)
used 2.17 and failed at the adapter's `_register_contract_types` call.
The adapter declares `SUPPORTED_RANGE = ">=2.0,<3"`; that broad statement does
not establish compatibility with every private API revision.
`uv.lock` already pins 2.15. The earlier real local adapter/report and Redline
CLI evidence succeeded with 2.15. Reuse it without another local application run.

The released narrow target is:
`tests/test_agent_workflow_ci.py::test_redline_installs_locked_import_linter`.
Existing controls to reuse include
`test_work_record_checker_accepts_valid_and_rejects_invalid`,
`test_redline_report_cli_calibration_matrix` in that same file, and
`tests/test_ci_workflow.py::test_aggregate_gate_accepts_only_complete_successful_required_lanes`.
They preserve valid/invalid checker, checkpoint and failed-required-lane behavior.
They are not substitutes for the real adapter report under hosted dependencies.
Any broader selector or platform validation remains coordinator-owned.
The focused command is
`python -m pytest --noconftest -q -n 0 tests/test_agent_workflow_ci.py::test_redline_installs_locked_import_linter`.
Its actual red/green results are below. The required architecture checkpoint
remains open; no review label, CI rerun or enforcement exception is asserted
or applied.

PR #417's first [application CI](https://github.com/rore/Pallium/actions/runs/44303987306)
completed with Linux 3.12 and Windows smoke passing, but Linux 3.13 failed:
3,892 passed, one failed, 29 skipped, one xfailed. In
`tests/test_dashboard.py::TestDashboardSourceAndRelayProjections::test_relay_fixed_window_excludes_concurrent_insert`,
the second setup send returned `503` at `late_begin`, with 449 ms
`begin_immediate`, before the paging oracle. No physical/common cause or
baseline waiver is established. Do not retry the unchanged head or alter that
fixture, oracle or timing budget. The earlier failed local full runs and old
capture/supersession failures remain separate.

The actual governance install log confirms 2.17, not a guessed dependency cause.
The completed first CI job conclusions and both Linux JUnit artifacts have been
retained privately. The local passing real-report receipt is reused; this plan
does not manufacture or substitute boundary evidence.

Upstream compatibility feedback remains a private unsent draft. No imported
content was patched and no public upstream issue was submitted.

## Review offer

The existing independent architect accepted the corrected CI requirements,
architecture/plan and actual source/verification scope. No blocking finding or
correction remained. No V2 review was repeated.

## Implementation release

Scoped plan review accepted the corrected CI-only requirements above. The
coordinator subsequently released implementation and bounded governance checks.
This record is updated before the first test or workflow edit. Prior plan-only
snapshots remain historical; do not restore the old copied feature baseline.
Actual scoped result review subsequently accepted the completed delta. The
repository checkpoint stays open until the authorized label is associated with
the verified published head; technical GO alone does not mutate that gate.

## Implementation and bounded results

Only the one workflow argument, one governance test and this record changed.
The test reads the actual YAML install step and unique TOML lock entry, then
collects all import-linter arguments before exact list equality. Bare, wrong,
missing or duplicate requirements cannot disappear from its check.

| Check | Actual result | Outer seconds |
| --- | --- | --- |
| New node before pin | One expected semantic failure: bare requirement versus locked 2.15 | 14.525 |
| Same node after pin | One passed | 1.669 |
| Affected governance file plus named aggregate control | 23 passed | 29.304 |
| Real unchanged import-linter adapter | Exit 0 and real report produced | 1.834 |

Each completed below its 240-second cap including drain, with zero owned
survivors. Pytest targets used `--noconftest -q -n 0`;
no application fixture or full suite was run. The affected file includes the
unchanged valid/invalid checker and Redline calibration controls. The real report
is independent of their synthetic boundary inputs.

Implementation is independently accepted, not merged or installed. State remains
Blocked pending the authorized repository checkpoint action, hosted governance
and required CI. No CI retry, maintained-content change or application correction
is part of this publication.

Whole-change selection includes the original candidate and this prerequisite:
eight paths, FULL lane. No local full run was started. The real report contains
no boundary violations. Redline reports RED for the governance workflow with
`architecture-review` unsatisfied. Agent Workflow validates both changed records
and returns advisory exit 1 for that open checkpoint, with no blocking failure.
No `--pr-labels` value, review label or fabricated verdict was supplied.
Hosted governance remains unproved until the reviewed update is published and
the existing workflow runs normally. The original failed hosted results are
not overwritten by these local checks.

## Result review

Independent actual architecture/source/verification-adequacy review accepted the
exact pin, contract and reviewed record at the stated base. It verified full
token collection, semantic red and unchanged-test green, 23 controls and the
separate real 2.15 report.
Reviewed workflow SHA-256:
`c35ed02d2387d8c1cc788ef03472de67859d1d1687b1206780b8ba238b4dcf8c`.
Reviewed test SHA-256:
`08b6a462605941df0b8c2e7e80c5622793fbf4277ca3896c97041c6890667d27`.
Publication changes only approved record metadata; those code bytes stay
unchanged. Hosted compatibility and the separate dashboard failure still need
their own evidence. Original V2 source/feature review is reused, not repeated.
