# Session participation lifecycle guidance

<!-- agent-workflow:start -->
**Outcome:** Agents maintain exact explicit work participation across session pickup, resume, and departure.
**Target:** Pallium packaged agent guidance.
**Scope:** The SKILL.md entrypoint and references/work-associations.md in integrations/{codex,claude-code,opencode}/skills/pallium-memory, tests/test_guidance_budget.py, plus this Work Record.
**Constraints:** Source prose only; preserve installed skills, live session links, services, user settings, unrelated references, and hook-owned structural origins.
**Completion criteria:** All three packages give the same canonical lifecycle procedure, reuse earlier-turn explicit links, and detach current-session explicit origins only when their assignments end.
**Requirement baseline:**
{"source":"parent-assignment-2026-10-20","outcome":"Agents maintain exact explicit work participation across session pickup, resume, and departure.","scope":"The SKILL.md entrypoint and references/work-associations.md in integrations/{codex,claude-code,opencode}/skills/pallium-memory, plus this Work Record.","constraints":"Source prose only; preserve installed skills, live session links, services, user settings, unrelated references, and hook-owned structural origins.","completion_criteria":"All three packages give the same canonical lifecycle procedure, reuse earlier-turn explicit links, and detach current-session explicit origins only when their assignments end."}
**Risk:** Elevated
**Behavior changes:** [{"classification":"coverage-only","target":"task-context.scope","before":"The SKILL.md entrypoint and references/work-associations.md in integrations/{codex,claude-code,opencode}/skills/pallium-memory, plus this Work Record.","after":"The SKILL.md entrypoint and references/work-associations.md in integrations/{codex,claude-code,opencode}/skills/pallium-memory, tests/test_guidance_budget.py, plus this Work Record.","reason":"Task owner explicitly authorized aligning stale guidance assertions with the already-approved lifecycle semantics while preserving all safety checks and the original byte ceiling."}]
**Complexity:** Simple
**Reason:** Packaged integration instruction paths are gray; no runtime, API, persistence, or protected behavior change.
**Discovery:** All runtime copies currently limit detach to links this flow attached. Codex/Claude hooks discover structural refs from branch and matching marked Work Record, without assignment-state checks. Minimap owns exact item identity; Pallium owns the lifecycle procedure.
**Material assumptions:** Existing APIs already preserve other origins and references; inspect and run bounded caller-surface tests. A contract gap returns to planning rather than expanding into runtime code.
**Plan:** Change the six scoped prose files only. Route entrypoint pickup/resume/departure to one generic procedure; remove duplicated Minimap detach instructions; keep missing-tool and capacity fallbacks. Stop if runtime changes prove necessary.
**Verification plan:** When a session resumes, guidance reuses existing current-session explicit refs and reconciles actual assignments -> cross-package diff review. When an assignment ends, detach preserves unrelated and structural refs -> existing isolated caller-surface lifecycle coverage. Run test-plan selector and workflow checks against the whole branch.
**Plan review:** Agent technical review: /root/participation_lifecycle/review approved at 1b1444c699ac3c2d42bc8724f28af7369c54e424 after inspecting this record, policy, and all six source files; no findings.
**Approvals:** Not required at this risk level.
**Exceptions:** —
**State:** Blocked
<!-- agent-workflow:end -->

## Implementation

Authorized test alignment: add tests/test_guidance_budget.py to this same task's scope (blue test path; the combined change remains Elevated/GRAY and full-lane). Restore Accepted assigned wording in the three entrypoints. Replace stale association assertions with the approved exact current-session lifecycle and preserve unrelated Relay, History, capacity, callable-tool, success-authority, participant, and Minimap safeguards. Obtain independent exact-diff review before one focused whole-file run, then independent actual-result assessment; publish only after GO. Retain all prior failed/timeout evidence and use ordinary new-head CI without another local full run.

PR #326 budget repair: automatic CI at 371707391b345e4a723e4bafa4735d574406d409 found the same entrypoint-size failure on Linux 3.12 and 3.13: 3118 LF-normalized UTF-8 bytes exceed the unchanged 3072-byte ceiling. The authorized repair shortens only the shared lifecycle bullet in the three packaged SKILL.md entrypoints, preserving accepted scope, exclusions, and canonical routing. The detailed work-associations references and their prior review remain unchanged. Before publication, run exactly tests/test_guidance_budget.py serially once, parity/diff/workflow checks, and an independent clean-context review of the new wording and actual result. No additional local full run, failed-head retry, manual CI dispatch, or installed change is authorized by this repair.

Created an isolated managed checkout from origin/main at 1b1444c699ac3c2d42bc8724f28af7369c54e424. Primary checkout dirty state remains untouched. Installed-copy sync is outside this task.

Implemented the six-file prose change after plan review. Removed the same-flow detach limitation and duplicated Minimap detach instructions. No roadmap state change: the existing shipped association feature remains shipped; this clarifies its agent guidance rather than reopening its runtime scope.

The verification selector classifies packaged integration Markdown as full-suite work. The delivery pickup attempted the required local full suite once through test execution; it stalled and reached the coordinator's 20-minute cap. Full validation remains incomplete. Do not call validation complete or merge on this record alone.

Trigger 4 dropped: the contradictory participation prose is owned and corrected in Pallium, not Agent Workflow upstream.

## Evidence

Aligned guidance verification after independent pre-run GO: tests/test_guidance_budget.py -q -n 0 --basetemp=build/pytest-guidance-aligned passed once, 11 passed in 0.91s (build/pr326-guidance-aligned-focused.txt). Package parity passes: three entrypoints are 3066 LF-normalized bytes under the unchanged 3072-byte ceiling, SHA-256 5a28c8cc543fedfbdd5ef77f4ed14d4bd22602b96afbd64b8fb75fddcdb27a9f. Detailed references retain their prior hash and review. Fresh whole-change Redline and workflow checks pass their applicable gates; full-lane selector remains authoritative. Earlier 2-failure focused output, local full timeout, and old-head hosted Linux budget failures remain evidence, not passes. Ordinary CI on the repaired published head is pending; keep State Blocked until qualification is assessed.

Budget repair against published 37170739 plus the three entrypoint bullets: tests/test_guidance_budget.py -q -n 0 --basetemp=build/pytest-guidance-budget ran once: 2 failed, 9 passed in 1.16s (build/pr326-budget-focused.txt). The byte ceiling now passes: all entrypoints are 3057 LF-normalized bytes, with parity across packages; the reference procedure remains unchanged at LF SHA-256 627b95022d8fda92b070235ae1fc9950866937dbbccac860b58f70f00ba884d9. git diff --check passes. The failed tests require old entrypoint strings (including optional continuity wording) and the old same-flow-only detach restriction; these conflict with the intended lifecycle change and were hidden behind the earlier full-suite first-failure stop. No test edits, further test run, publication, or claim of completed validation follows this failure. The task remains Blocked pending explicit reconciliation of guidance-test scope and independent review.

Delivery pickup: the reviewed source commit is e10bb59ebb20edfb3cb3faea2dc7ce4099d7e9ee. A separate Git checkout at C:/Dev/rore/Pallium/build/participation-lifecycle-delivery preserves the original checkout. Publication retains remote branch feat/participation-lifecycle and this Work Record identity; the local delivery branch is feat/participation-lifecycle-delivery. The six source files remain unchanged. Their recorded reference hash is LF-normalized; checkout CRLF bytes differ without changing Git content.

The whole-change selector again selects full validation. Two launches failed before collection because the sandbox default temporary directory was unavailable, then because the isolated build parent did not exist. After creating that parent, C:/Dev/rore/Pallium/.venv/Scripts/python.exe -m pytest tests/ -x -q --basetemp=build/pytest-full started at 2026-10-20T17:17:34+03:00 in the delivery checkout against e10bb59e plus this Work Record prose. It emitted progress below 1% and then stalled. The coordinator imposed a 20-minute cap at 17:37:34; verified owned root PID 38812 and its ten descendants were stopped at 17:37:43 after identity checks. Readback found no owned test processes remaining. No test failure or passing summary was produced. Result: TIMEOUT_INCOMPLETE; no automatic rerun.

Local evidence remains in build/full-suite-state.json, build/full-suite-output.txt, build/full-suite-owned-tree.json, and build/full-suite-terminal.json. Fresh changed-path Redline remains GRAY with no boundary violations, reusing the unchanged import-linter evidence; the existing Work Record check returned clean. Installed behavior and real-use agent adoption remain unverified; no live associations or installed files were changed. Publication was not executed: automatic permission review timed out twice before the Git commit/push command started. The coordinator owns final publication and must disclose the incomplete full-suite gate.

Against 1b1444c699ac3c2d42bc8724f28af7369c54e424 plus this six-file prose diff: byte parity across all three runtime packages and git diff --check pass. Three existing HTTP E2E nodes pass (3 passed in 3.27s): attach_overlap_overflow_detach_and_exact_participants; structural_refresh_is_replace_only_and_failure_does_not_block_turn; alias_transfer_does_not_transfer_associations_and_reopen_retains_them.

Additional bounded caller-surface check passed using the existing TestClient fixture and temporary SQLite only: register with structural branch/feature refs, attach feature and unrelated explicit refs, admit next turn, list unchanged existing single feature explicit origin, detach feature explicit origin, read back exactly the previous state minus that explicit origin with structural_remains=true. No live links, service, paid model calls, or installed skills were used. Initial attempt lacked the local build directory; created that isolated output directory and reran successfully.

Fresh changed-path Redline verdict and import-linter report generated; agent-workflow-runtime.ps1 codex check --repo-root . --slug participation-lifecycle returned clean. Full selector lane remains pending as above.

## Result review

Aligned guidance independent clean-context review: /root/lifecycle_delivery/budget_review gave pre-run GO on the exact source/test diff against 37170739, then final GO after inspecting the retained 11-passed focused output and parity report. Reviewed revision: 37170739 plus the three entrypoint, tests/test_guidance_budget.py, and Work Record diff; entrypoint hash 5a28c8cc543fedfbdd5ef77f4ed14d4bd22602b96afbd64b8fb75fddcdb27a9f. The assigned qualifier finding below is resolved. Verification adequacy: focused evidence covers the budget repair and aligned safety/lifecycle assertions; prior detailed-procedure review is reused. Full qualification remains pending ordinary new-head CI and must retain the incomplete local full run honestly.

Budget repair independent clean-context review: /root/lifecycle_delivery/budget_review inspected 37170739 plus the three shortened entrypoint bullets and build/pr326-budget-focused.txt. NO GO: retain an explicit assigned-work qualifier alongside accepted-work scope; the 3057-byte version says only Accepted implementation. The focused run establishes byte-budget compliance but is not passing validation; stale entrypoint and prior same-flow detach assertions require a deliberate scope decision before test changes. No runtime or installed-environment expansion is justified.

Agent technical review: /root/participation_lifecycle/review; no substantive findings after inspecting all six changed source files and byte parity against the base checkout.

Reviewed revision: 1b1444c699ac3c2d42bc8724f28af7369c54e424 plus the six-file prose diff (entrypoint SHA-256 3884C151897A53335BAE6C67FE2E1A3AECB5EBA377183DAE69CC1A144FD3DB58; reference SHA-256 627B95022D8FDA92B070235AE1FC9950866937DBBCCAC860B58F70F00BA884D9).

Verification adequacy: bounded HTTP evidence directly covers the requested lifecycle, and source review found no scope expansion. Selector-reported full validation is still required; result approval is limited to the source guidance and does not claim that validation complete.
