# Session participation lifecycle guidance

<!-- agent-workflow:start -->
**Outcome:** Agents maintain exact explicit work participation across session pickup, resume, and departure.
**Target:** Pallium packaged agent guidance.
**Scope:** The SKILL.md entrypoint and references/work-associations.md in integrations/{codex,claude-code,opencode}/skills/pallium-memory, plus this Work Record.
**Constraints:** Source prose only; preserve installed skills, live session links, services, user settings, unrelated references, and hook-owned structural origins.
**Completion criteria:** All three packages give the same canonical lifecycle procedure, reuse earlier-turn explicit links, and detach current-session explicit origins only when their assignments end.
**Requirement baseline:**
{"source":"parent-assignment-2026-10-20","outcome":"Agents maintain exact explicit work participation across session pickup, resume, and departure.","scope":"The SKILL.md entrypoint and references/work-associations.md in integrations/{codex,claude-code,opencode}/skills/pallium-memory, plus this Work Record.","constraints":"Source prose only; preserve installed skills, live session links, services, user settings, unrelated references, and hook-owned structural origins.","completion_criteria":"All three packages give the same canonical lifecycle procedure, reuse earlier-turn explicit links, and detach current-session explicit origins only when their assignments end."}
**Risk:** Elevated
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

Created an isolated managed checkout from origin/main at 1b1444c699ac3c2d42bc8724f28af7369c54e424. Primary checkout dirty state remains untouched. Installed-copy sync is outside this task.

Implemented the six-file prose change after plan review. Removed the same-flow detach limitation and duplicated Minimap detach instructions. No roadmap state change: the existing shipped association feature remains shipped; this clarifies its agent guidance rather than reopening its runtime scope.

The verification selector classifies packaged integration Markdown as full-suite work. The lead explicitly requested no duplicate native full suite; that required validation remains pending the lead's evidence/CI decision. Do not call validation complete or merge on this record alone.

Trigger 4 dropped: the contradictory participation prose is owned and corrected in Pallium, not Agent Workflow upstream.

## Evidence

Against 1b1444c699ac3c2d42bc8724f28af7369c54e424 plus this six-file prose diff: byte parity across all three runtime packages and git diff --check pass. Three existing HTTP E2E nodes pass (3 passed in 3.27s): attach_overlap_overflow_detach_and_exact_participants; structural_refresh_is_replace_only_and_failure_does_not_block_turn; alias_transfer_does_not_transfer_associations_and_reopen_retains_them.

Additional bounded caller-surface check passed using the existing TestClient fixture and temporary SQLite only: register with structural branch/feature refs, attach feature and unrelated explicit refs, admit next turn, list unchanged existing single feature explicit origin, detach feature explicit origin, read back exactly the previous state minus that explicit origin with structural_remains=true. No live links, service, paid model calls, or installed skills were used. Initial attempt lacked the local build directory; created that isolated output directory and reran successfully.

Fresh changed-path Redline verdict and import-linter report generated; agent-workflow-runtime.ps1 codex check --repo-root . --slug participation-lifecycle returned clean. Full selector lane remains pending as above.

## Result review

Agent technical review: /root/participation_lifecycle/review; no substantive findings after inspecting all six changed source files and byte parity against the base checkout.

Reviewed revision: 1b1444c699ac3c2d42bc8724f28af7369c54e424 plus the six-file prose diff (entrypoint SHA-256 3884C151897A53335BAE6C67FE2E1A3AECB5EBA377183DAE69CC1A144FD3DB58; reference SHA-256 627B95022D8FDA92B070235AE1FC9950866937DBBCCAC860B58F70F00BA884D9).

Verification adequacy: bounded HTTP evidence directly covers the requested lifecycle, and source review found no scope expansion. Selector-reported full validation is still required; result approval is limited to the source guidance and does not claim that validation complete.
