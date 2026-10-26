<!-- agent-workflow:start -->
**Outcome:** Agents discover the globally installed persistent-agent-roles skill at work boundaries.
**Target:** Pallium agent instructions.
**Scope:** AGENTS.md and this Work Record.
**Constraints:** No vendored skill, mappings, runtime, service, integration or global configuration changes.
**Completion criteria:** One concise canonical note names the skill, entry boundaries and global installation source without duplication.
**Requirement baseline:**
{"source":"Astra user-authorized bounded assignment","outcome":"Agents discover the globally installed persistent-agent-roles skill at work boundaries.","scope":"AGENTS.md and this Work Record.","constraints":"No vendored skill, mappings, runtime, service, integration or global configuration changes.","completion_criteria":"One concise canonical note names the skill, entry boundaries and global installation source without duplication."}
**Relationships:**
{"schema_version":1,"sources":null,"pull_requests":[]}
**Risk:** Elevated
**Complexity:** Simple
**Reason:** Agent instructions are non-exempt governance; AGENTS.md is unclassified gray.
**Discovery:** No existing role-skill trigger. CLAUDE.md already requires AGENTS.md, so no mirror is needed.
**Material assumptions:** The globally installed skill remains the maintained implementation; this change only supplies discovery guidance.
**Plan:** Add the requested paragraph near the start of AGENTS.md; inspect the exact diff and whitespace. Do not copy the skill or create mappings.
**Verification plan:** One concise canonical note without duplication -> inspect single occurrence, existing CLAUDE.md reference, exact two-path diff and git diff --check.
**Plan review:**Agent technical review: existing Astra reviewer, 2026-10-26, GO for the exact paragraph and Work Record only; reuse CLAUDE.md linkage, focused governance/diff checks, no application tests.
**Approvals:** Not required at this risk level; task explicitly authorized by user through Astra.
**Exceptions:** —
**State:** Ready for review
<!-- agent-workflow:end -->

## Result review
Agent technical review: Astra independently inspected the actual diff and status on 2026-10-26: GO for the exact paragraph and required Work Record, with no duplicate mirror.
Reviewed revision: ce0943de (reviewed paragraph unchanged after merging main).
Verification adequacy: Exact diff, single occurrence and canonical linkage inspected by Astra; focused governance selected. Application tests not applicable to instruction-only change.

**Evidence:** Exact paragraph occurs once; CLAUDE.md already references AGENTS.md; git diff --check passed. scripts/test-plan.py selected governance only. Selected tests/test_test_plan.py, tests/test_ci_workflow.py and tests/test_agent_workflow_ci.py ended with 15 passed, 22 setup errors in 46.89s (exit 1). A bounded elevated rerun for publication passed all 37 selected tests in 71.26s; no unrelated fixes or application tests. Log: build/governance-publication.log.
**Delivery:** The same reviewed paragraph was surgically applied to the primary checkout under Astra's explicit instruction, preserving other work. Publication remains separate and has not occurred.
