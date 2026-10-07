## Implementation

The exact 45 upstream Git blobs from Minimap commit `afbec2142c6674fde9e4b643dbf4e13b3284bc7c` are now in `.claude/skills/minimap-roadmap/`; every local blob and the full manifest match. Added an AGENTS.md pointer to that existing folder and expanded the CLAUDE.md trigger. Whole-change selector required the full suite: 6,341 passed, 34 skipped, 2 xfailed. Fresh import-boundary, Redline, implementation-ready workflow, local workflow-wrapper, and diff-hygiene checks passed. Awaiting independent result review. Branch `feat/pallium-minimap-roadmap-skill-refresh` is based on `f062cc72abaa59c523bee23bd565cdfc9546cedb` (`origin/main`).

<!-- agent-workflow:start -->
**Outcome:** Pallium's existing Minimap roadmap skill and its discovery guidance reflect the approved upstream assigned-work behavior and current runtime package.

**Target:** Pallium repository.

**Scope:** Replace the tracked `.claude/skills/minimap-roadmap/` tree with the exact tree from Minimap commit `afbec2142c6674fde9e4b643dbf4e13b3284bc7c`; add an AGENTS.md pointer to that existing skill; broaden the CLAUDE.md trigger for assigned roadmap work.

**Constraints:** Do not change roadmap state or Pallium associations, create a duplicate skill, or change setup/install behavior, hooks, config, services, or stable checkouts. Keep exact reference production, optional MCP-only participation, successful self attach/detach, capacity safeguards, and existing safety guidance. Stop if source or scope assumptions fail.

**Completion criteria:** The full tracked skill tree matches Minimap's exact requested commit; AGENTS.md and CLAUDE.md discover the existing skill for roadmap edits and assigned pickup, resume, investigation, testing, substantive review, and completion; required whole-change selector checks pass; no unrelated paths change.

**Requirement baseline:**
{"source":"work-record-initial","outcome":"Pallium's existing Minimap roadmap skill and its discovery guidance reflect the approved upstream assigned-work behavior and current runtime package.","scope":"Replace the tracked `.claude/skills/minimap-roadmap/` tree with the exact tree from Minimap commit `afbec2142c6674fde9e4b643dbf4e13b3284bc7c`; add an AGENTS.md pointer to that existing skill; broaden the CLAUDE.md trigger for assigned roadmap work.","constraints":"Do not change roadmap state or Pallium associations, create a duplicate skill, or change setup/install behavior, hooks, config, services, or stable checkouts. Keep exact reference production, optional MCP-only participation, successful self attach/detach, capacity safeguards, and existing safety guidance. Stop if source or scope assumptions fail.","completion_criteria":"The full tracked skill tree matches Minimap's exact requested commit; AGENTS.md and CLAUDE.md discover the existing skill for roadmap edits and assigned pickup, resume, investigation, testing, substantive review, and completion; required whole-change selector checks pass; no unrelated paths change."}

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Redline classifies the vendored skill and root agent guidance as GRAY/watch paths, which sets an Elevated floor. The exact upstream refresh spans 45 files including a substantial runtime mirror, plus two guidance pointers, with selector-driven validation.

**Discovery:** Pallium tracks 38 skill files (727,609 bytes); Minimap's exact upstream tree has 45 (860,205 bytes), with 20 differing overlaps, 7 upstream-only paths, and 18 matching overlaps. There are no Pallium-only paths. The 34-file upstream runtime mirror has zero blob mismatches against canonical `package/minimap/` at the requested commit, generated via `scripts/sync-mirrors.mjs`. The upstream Pallium participation reference preserves exact item-ref production, MCP-only optionality, and attach/detach/capacity safety while adding assigned investigation/testing and current participant-panel semantics. The docs-only applicability exemption is denied because these are protected/unapproved vendored and agent-instruction paths. Intended 47-path Redline result is GRAY with no red paths, checkpoints, or boundary violations; import-linter passed using the existing repository venv.

**Material assumptions:** No local-only vendor files or additional canonical skill copies are tracked; verified with `git ls-tree`. The approved exact-source refresh is intended to replace older content in overlapping files; recheck the final diff for preserved Pallium safeguards before proceeding.

**Plan:** Copy exactly the 45 tracked skill files from the pinned Minimap commit using Git blobs. Add one concise AGENTS.md pointer to the existing `.claude/skills/minimap-roadmap/SKILL.md` and broaden the CLAUDE.md trigger for assigned roadmap work without adding another install. Keep all other paths unchanged. Run whole-change applicability/Redline and test-plan selection; execute the selected validation, workflow checks, and diff hygiene. Stop if the pinned source changes, a Pallium safeguard is absent, the selector expands scope unexpectedly, or tests reveal an unresolved regression.

**Verification plan:** Exact vendor paths and blobs match the pinned upstream tree → compare path manifests and Git blob IDs. Runtime blobs also match canonical upstream package source → compare all runtime files against `package/minimap/`. Guidance points to the existing skill and covers assigned-work triggers while preserving casual browsing/passive inspection/clerical exclusions → inspect the final diff and tracked path inventory. Required whole-change checks pass and no unrelated paths change → run `scripts/test-plan.py --base origin/main`, follow its selection, and run workflow/Redline checks plus `git diff --check`.

**Plan review:** Agent technical review: independent non-implementer reviewer approved the exact-source refresh and pointer scope before implementation on 2026-10-07.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Result review

Agent technical review: independent non-implementer reviewer accepted the vendor refresh, guidance pointers, and retained participant safety.

Reviewed revision: full change diff based on `f062cc72abaa59c523bee23bd565cdfc9546cedb`, with the exact skill source pinned at Minimap `afbec2142c6674fde9e4b643dbf4e13b3284bc7c`.

Verification adequacy: adequate for this scope. The whole-change selector-required Pallium suite passed (6,341 passed, 34 skipped, 2 xfailed); all 45 vendor files match their upstream blobs; Redline, import-boundary, workflow, and diff checks passed. No installed-consumer behavior was exercised or refreshed.

Findings: no blocking findings.

## Evidence

- Redline: `build/minimap-skill-refresh-redline.json` (intended paths, 47 files; GRAY, no checkpoint or boundary finding).
- Boundary backend: `build/import-linter-report.json` (existing repository venv; pass).
- Applicability: workflow checker denies documentation-only exemption for protected paths; whole-change workflow check passes with the Work Record and Redline evidence.
- Test selector: `scripts/test-plan.py --base origin/main` selected `python -m pytest tests/ -x -q`; result 6,341 passed, 34 skipped, 2 xfailed.
- Final workflow check: `scripts/agent-workflow-runtime.ps1 codex check` with the actual changed-path list and Redline verdict; pass. `git diff --check`; pass.
- Upstream source: Minimap commit `afbec2142c6674fde9e4b643dbf4e13b3284bc7c`.
