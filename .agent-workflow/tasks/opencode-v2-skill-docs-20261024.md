<!-- agent-workflow:start -->
**Outcome:**
OpenCode setup guidance distinguishes V1 automatic Pallium skill/command registration from V2 native explicit skill discovery and does not imply that a blocked V2 runtime qualification succeeded.

**Target:**
Pallium OpenCode integration documentation.

**Scope:**
`integrations/opencode/README.md` and this Work Record only.

**Constraints:**
Preserve V1 setup; do not change integration code, installed user configuration, the shared checkout, or the frozen qualification checkout. Do not conflate Pallium's `pallium-memory` skill with the collection's separate `persistent-agent-roles` skill or claim installed V2 discovery from a staged fixture.

**Completion criteria:**
The README's V2 local-checkout example matches primary V2 `mcp.servers` and `skills` syntax, and its text correctly states the V1-only automatic registration and V2 explicit skill setup; the focused documentation/workflow checks and independent actual-diff review pass.

**Requirement baseline:**
{"source":"codex-thread:01a15fcd-b512-70d8-81fb-265c0dbac00f","outcome":"OpenCode setup guidance distinguishes V1 automatic Pallium skill/command registration from V2 native explicit skill discovery and does not imply that a blocked V2 runtime qualification succeeded.","scope":"`integrations/opencode/README.md` and this Work Record only.","constraints":"Preserve V1 setup; do not change integration code, installed user configuration, the shared checkout, or the frozen qualification checkout. Do not conflate Pallium's `pallium-memory` skill with the collection's separate `persistent-agent-roles` skill or claim installed V2 discovery from a staged fixture.","completion_criteria":"The README's V2 local-checkout example matches primary V2 `mcp.servers` and `skills` syntax, and its text correctly states the V1-only automatic registration and V2 explicit skill setup; the focused documentation/workflow checks and independent actual-diff review pass."}

**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}

**Risk:** Elevated

**Complexity:** Simple

**Reason:**
`integrations/opencode/README.md` is not in Redline's blue allowlist, so its unclassified gray path sets an Elevated floor. The change is one documentation correction with no runtime or protected-contract edit.

**Discovery:**
At pinned `origin/main` `fd14a77d19713e878105a537de0dfee9735dc88e`, README lines 125-127 claim automatic skill and command registration after both loader examples. V1 `pallium.mjs` has the config hook that adds both; V2 `server.js` exports `pallium-v2.mjs`, which has no equivalent registration. Primary V2 docs put server names under `mcp.servers`, allow explicit `skills` directories, resolve those directories from the active working directory, and resolve local plugin paths from the config file. Both isolated 2.0.25 probes stopped before OpenCode launched, so they provide no installed discovery evidence. The related collection role feature is `rore/rore-collection:plans/feature-persistent-agent-roles.md` (id `persistent-agent-roles`, still planned); its role skill and `roles/mapping.yaml` are separate from Pallium's skill.

**Material assumptions:**
The README's V2 example is for a project-root `opencode.jsonc` in the same checkout, so its relative plugin and skill paths point to the shown directories. If review finds a different intended config location, revise the example before editing or publishing. Current primary V2 documentation is source-level evidence only; a native 2.0.25 roster result remains unavailable.

**Plan:**
1. Leave the V1 example unchanged. In the V2 local-checkout example, use documented `mcp.servers.pallium` (without V1 `enabled`) and add an explicit native `skills` source for `./integrations/opencode/skills`; explain that relative skill sources use the working directory while plugin paths use the config file location.
2. Replace the blanket sentence with V1-only automatic `pallium-memory` skill and `/pallium-memory` command registration, V2 explicit native skill setup, and the distinction that AGENTS guidance triggers loading but does not install either skill. Do not promise V2 command registration or collection role installation.
3. Keep blocked-probe detail in this Work Record, not setup prose. Stop if a change beyond this README or a runtime/config mutation becomes necessary.

**Verification plan:**
V2 example syntax and source distinction → primary V2 skills/MCP/plugin docs, JSON parse, and independent actual-diff review.
Declared scope and governance → fresh Redline and Agent Workflow checks plus diff inspection.
Repository validation → `scripts/test-plan.py --base origin/main` and its selected checks.

**Plan review:** Agent technical review: `/root/opencode_docs_plan_review` (2026-10-24), GO. It checked base `fd14a77d19713e878105a537de0dfee9735dc88e`, the Work Record, both adapter sources, the README, and primary V2 docs; no material blocker. The JSONC sample is strict-JSON-compatible, so JSON parsing remains a valid check.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Blocked
<!-- agent-workflow:end -->

## Related feature

Collection canonical role feature: `rore/rore-collection:plans/feature-persistent-agent-roles.md` (`id: persistent-agent-roles`). Pallium does not own role-file interpretation or role registration. A provider-issued relationship tuple was not supplied, so `Relationships.sources` remains unresolved rather than guessed.

## Implementation

Planning record created before README edit on isolated `feat/opencode-v2-skill-docs-20261024` from `fd14a77d19713e878105a537de0dfee9735dc88e`. Independent plan review returned GO. Implementation modified only `integrations/opencode/README.md` and this Work Record. The README now distinguishes V1 automatic registration from V2 explicit skill setup, uses V2 `mcp.servers`, and matches V2 removal instructions; no runtime or installed configuration changed under this task.

Trigger 3 dropped: local pytest temp-path and missing-`pyte` failures are test-environment conditions, not an Agent Workflow skill defect.

Coordinator disposition (2026-10-24): commit and push this reviewed source checkpoint while State remains `Blocked`; verify its exact remote head, then run one standard hosted full suite on that head before creating any PR. A draft PR does not waive the pre-PR check. No local dependency installation, selector change, or OpenCode runtime action is part of this checkpoint.

## Evidence

Primary V2 documentation: https://dev.opencode.ai/v2/docs/skills/ ; https://dev.opencode.ai/v2/docs/mcp-servers/ ; https://dev.opencode.ai/v2/docs/plugins/ . The prior task-owned OpenCode receipts under ignored `build/` recorded `attempts=0`; a separately authorized later roster attempt stopped before any model turn and does not establish installed V2 discovery. The V2 JSON block parsed and key paths matched the intended values; `git diff --check` passed. Redline reported an Elevated gray-path advisory, no boundary violation, and Agent Workflow reported clean with that fresh verdict. Focused `tests/test_agent_workflow_ci.py` passed (19 tests). `scripts/test-plan.py --base origin/main` selected full `pytest tests/ -x -q`; first attempts ran zero tests because pytest could not create the sandbox temp path, and the corrected task-local temp run reached collection but stopped at `tests/test_hermes_terminal_screen.py` with `ModuleNotFoundError: pyte` in the existing virtual environment. No dependency was installed. Required full validation remains unsatisfied; next step is the coordinator-approved standard hosted full run on the exact pushed head.

Repository policy: `integrations/opencode/README.md` is outside `agent-workflow.yaml`'s documentation-only allowlist, so the whole change uses this Work Record and PR path. `AGENTS.md` requires `scripts/test-plan.py --base origin/main` and its reported checks before review or PR; it requires a full non-slow suite for application, mixed, unknown, selector, CI, or shared-configuration changes. This README plus Work Record is selected as `lane=full` (`reason=application, mixed, runtime, or unrecognized paths changed`). The coordinator's hosted-full route is the pending exact-head validation, not an exemption or a claim that the local failed run passed.

## Result review

Agent technical review: `/root/opencode_docs_result_review` (2026-10-24), HOLD on verification adequacy only. Reviewed revision: working-tree diff against `fd14a77d19713e878105a537de0dfee9735dc88e`. The reviewer found the V1/V2 registration distinction, V2 config paths, MCP schema, removal guidance, and no installed-runtime claim technically correct. A second nonimplementer review by `@astra-reviewer` found no substantive README issue. Verification adequacy: focused source, JSON, diff, Redline, Agent Workflow, and 19 focused governance tests support the documentation wording, but the selector-required full suite has not run to a product result because this local environment lacks `pyte`. The reviewed source checkpoint may be committed and pushed for exact-head hosted qualification; no Ready-for-review claim or PR until that gate is resolved.
