<!-- agent-workflow:start -->
**Outcome:**
OpenCode guidance tells users to configure one Pallium adapter across all applicable config roots and plugin copies.

**Target:**
Pallium OpenCode integration documentation.

**Scope:**
`integrations/opencode/README.md` and this Work Record.

**Constraints:**
Documentation only. No automatic cleanup, setup command, doctor, settings, framework, host or service changes. State the V1 report and V2 uncertainty without claiming reproduction.

**Completion criteria:**
The README says to configure exactly one Pallium adapter across applicable default/custom `OPENCODE_CONFIG_DIR` and project configs, including physical copies, and distinguishes the unreproduced V1 report from unverified V2 dual-root behavior.

**Requirement baseline:**
{"source":"parent task assignment","outcome":"OpenCode guidance tells users to configure one Pallium adapter across all applicable config roots and plugin copies.","scope":"`integrations/opencode/README.md` and this Work Record.","constraints":"Documentation only. No automatic cleanup, setup command, doctor, settings, framework, host or service changes. State the V1 report and V2 uncertainty without claiming reproduction.","completion_criteria":"The README says to configure exactly one Pallium adapter across applicable default/custom `OPENCODE_CONFIG_DIR` and project configs, including physical copies, and distinguishes the unreproduced V1 report from unverified V2 dual-root behavior."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Simple

**Reason:**
The nested integration README is gray under Redline: the policy's `README.md` blue glob matches only the root README. No API, persistence, security, runtime configuration, or dependency boundary is touched.

**Discovery:**
The existing README says not to load V1 and V2 in one configuration, but does not cover multiple effective plugin sources or physical copies. The OpenCode docs describe plugin loading from global and project sources and a custom `OPENCODE_CONFIG_DIR`. The repository's documentation-only applicability allowlist excludes this nested README, so a Work Record and normal workflow apply.

**Material assumptions:**
The new text will describe conservative setup guidance and evidence limits only; it will not assert that Pallium reproduces the upstream V1 report or that V2 dual-root loading is safe. If source evidence contradicts those limits, stop and return for scope review.

**Plan:**
Add one concise note beside the V1/V2 loader examples covering the default user, custom `OPENCODE_CONFIG_DIR`, project roots, and different physical copies. State that the upstream V1 duplicate-loading report is not reproduced in Pallium and V2 multi-root behavior is unverified. Any old-copy removal remains manual, limited to an identified obsolete copy the user controls, and approval-dependent.

**Verification plan:**
The README covers every requested config source, adapter version, and evidence limit → inspect the exact diff. Documentation and record remain the only changed paths → whole-change selector and workflow/Redline checks.

**Plan review:**
Agent technical review: `/root/role_history_developer/role_history_plan_review` — GO on plan at `b1880e976b637783cc0f46ee030a9c1a98767c1`. Reviewer advised saying one adapter should be discoverable/loaded across applicable sources, without implying configuration roots are independent copies, and linking the upstream report.

**Approvals:**
Not required at this risk level.

**Exceptions:**
—

**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Plan review passed. The README adds exactly two sentences covering applicable roots and physical copies, the unreproduced upstream V1 report, unverified V2 multi-root behavior, and approval-dependent removal of an identified obsolete copy the user controls. No application behavior or configuration was changed.

## Evidence

`git diff --check` passed. `scripts/test-plan.py --base origin/main` selected the full lane (`python -m pytest tests/ -x -q`) because it classified the nested integration README and Work Record as unrecognized paths; no application suite was run under the parent’s explicit no-broad-tests scope. The local workflow check was attempted and exited 2: the repository requires a Redline verdict, but the configured import-linter report was absent; the checker also found a task-context mismatch, which was corrected in the baseline above. No passing workflow/Redline result is claimed.

## Result review

Agent technical review: `/root/role_history_developer/role_history_plan_review` — GO on the actual diff at `b1880e976b637783cc0f46ee030a9c1a98767c1`. The reviewer approved the wording and scope, asked that “managed copy” be replaced with “copy you control,” and confirmed the upstream report is linked, Pallium non-reproduction is stated, and V2 multi-root behavior remains unverified. The reviewer could not attest the full selector check or a Redline result. Remaining: obtain valid repository Redline evidence and the selected full-lane validation before marking Ready for review.
