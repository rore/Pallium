# Update minimap skill to latest version

<!-- agent-workflow:start -->
**Outcome:** `.claude/skills/minimap-roadmap/` in the repo is synced to the latest version from the local clone; the new `minimap-spec-review` skill is installed to the user-level Claude skills directory (`C:\Users\I347041\.claude\skills\`).

**Target:** rore/pallium repo — `.claude/skills/minimap-roadmap/**`; user-level Claude config — `C:\Users\I347041\.claude\skills\minimap-spec-review\`.

**Scope:** (Repo, PR) Overwrite all files in `.claude/skills/minimap-roadmap/` from `C:\Dev\rore\minimap\package\minimap\skills\minimap-roadmap\` (30 files, all differ). (User, outside repo) Copy `minimap-spec-review` skill tree from `C:\Dev\rore\minimap\package\minimap\skills\minimap-spec-review\` into `C:\Users\I347041\.claude\skills\minimap-spec-review\` (new directory, 32 files). NOT in scope: `CLAUDE.md`, no Pallium Python code, no CI workflows, no `agent-redline-policy.yaml`, no `agent-workflow.yaml`, no existing `.claude/skills/agent-workflow/**`.

**Constraints:** Changes must be mechanical (upstream content only — no local edits to skill files). User-level copy is outside the repo — not committed, not CI-gated. Do not alter any other installed skills.

**Completion criteria:** `diff -rq` between `.claude/skills/minimap-roadmap/` and package source returns clean; `diff -rq` between `C:\Users\I347041\.claude\skills\minimap-spec-review\` and package source returns clean; CI green (agent-workflow + redline + test + windows-smoke gates pass on the PR).

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `.claude/skills/**` is in the redline `excludes` list — no zone classification for those paths. The Work Record itself is gray (unmatched). Any gray path → Elevated. No red-zone path touched. Simple: two directory copies, one session.

**Discovery:** `diff -rq` shows all 30 files in `minimap-roadmap` differ from installed. Package contains a second skill `minimap-spec-review` (32 files) absent from both repo and user-level skills. `minimap-roadmap` is repo-scoped (committed under `.claude/skills/`); `minimap-spec-review` is user-scoped (goes to `C:\Users\I347041\.claude\skills\`, not committed to repo). User skills currently: `scenario-tests` only. Local minimap clone at `main @ 06ac46d`.

**Material assumptions:**
- Both skill trees are self-contained drop-in copies (no path rewiring needed). Disproved by: diff after copy showing broken cross-references → action: inspect and fix paths.
- The new `minimap-spec-review` skill is ready for general use (no draft marker). Confirmed: SKILL.md frontmatter has only `name` and `description`, no `draft`/`wip` field.

**Plan:** (1) Overwrite `.claude/skills/minimap-roadmap/` in the repo from package source via robocopy. (2) Copy `minimap-spec-review/` to `C:\Users\I347041\.claude\skills\minimap-spec-review\` from package source (user context, outside repo). (3) Verify both trees via diff. Stop condition: any post-copy diff is non-empty.

**Verification plan:** Local — `diff -rq .claude/skills/minimap-roadmap <package source>` = clean; `diff -rq C:\Users\I347041\.claude\skills\minimap-spec-review <package source>` = clean; `python scripts/agent-workflow-check.py --slug update-minimap-skill` passes shape/field predicates. CI — `agent-workflow` + `redline` + `test (3.12)` + `test (3.13)` + `windows-smoke` green on the PR.

**Plan review:** clean-context Explore subagent review (Elevated requirement). See `## Plan review` below.

**Approvals:** Not required at this risk level (Elevated).

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

Synced from `C:\Dev\rore\minimap` (main @ 06ac46d). Mechanical, upstream content only:
- Overwrote `.claude/skills/minimap-roadmap/` (30 files) from `package/minimap/skills/minimap-roadmap/` via robocopy.
- Installed `C:\Users\I347041\.claude\skills\minimap-spec-review/` (32 files, new) from `package/minimap/skills/minimap-spec-review/` — user context, outside repo.

## Evidence (local verification)

- `diff -rq .claude/skills/minimap-roadmap <package source>` → IDENTICAL
- `diff -rq C:\Users\I347041\.claude\skills\minimap-spec-review <package source>` → IDENTICAL

## Plan review

Clean-context review (Explore subagent, read-only) — **verdict: sound-with-nits** on the original plan. Revised scope (user-context split) makes two of the nits moot; one note survives:

- The `minimap-roadmap` copy target in `.claude/skills/` is `excludes`-listed in redline and carries no stale files to delete — clean overwrite is safe.
- `minimap-spec-review` going to user context (`C:\Users\I347041\.claude\skills\`) is outside the repo and not CI-gated — correct placement per design.
- No red-zone paths in scope. Risk: Elevated from the gray WR file. Simple complexity confirmed.
