# Cross-agent skill fallback

<!-- agent-workflow:start -->
**Outcome:** Codex follows the repository's canonical agent-workflow skill even when it is absent from Codex's advertised skill catalog.

**Target:** Pallium repository agent guidance.

**Scope:** `AGENTS.md` and this Work Record only.

**Constraints:** Keep `.claude/skills/agent-workflow/` as the single canonical skill copy; do not duplicate, repackage, or alter the skill.

**Completion criteria:** When a runtime cannot invoke `/agent-workflow`, `AGENTS.md` shall direct it to read the canonical `SKILL.md` and resolve all referenced resources relative to that directory.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** `AGENTS.md` is unclassified by redline and therefore gray/Elevated; the change is one documentation instruction with no runtime code impact. The preferred clean-context classifier was attempted but blocked by Windows process error 1385.

**Discovery:** The skill exists only at `.claude/skills/agent-workflow/SKILL.md`; neither repo-local nor user-level Codex skill discovery contains it. Pallium's Codex setup installs only `pallium-memory`. The existing `AGENTS.md` instruction names `/agent-workflow` but provides no path fallback.

**Material assumptions:** Codex can read repo files explicitly named by `AGENTS.md`; disproved if a fresh Codex task cannot open the canonical path, in which case native Codex registration is required.

**Plan:** Add one fallback sentence beside the existing `/agent-workflow` instruction. Do not change skill packaging, hooks, or workflow behavior. Stop if clean-context review identifies a cross-runtime incompatibility.

**Verification plan:** Completion criterion -> inspect the final `AGENTS.md` wording and run `python scripts/agent-workflow-check.py --repo-root . --slug cross-agent-skill-fallback`.

**Plan review:** Clean-context `/root/review_fallback_plan`: no blockers; approved to implement.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Established context and conservatively classified `AGENTS.md` as gray/Elevated before editing it.
- Clean-context redline classification was attempted; the reviewer could not access files because Windows rejected process creation with error 1385.
- Implementation note: added the runtime fallback sentence to `AGENTS.md` immediately after the `/agent-workflow` instruction.
- Verification completed against HEAD `452ca63de4168dca24fff926d9534e3fd1ed7aa4`: redline verdict is GRAY with no boundary violations; workflow check passed; `git diff --check` passed.
- Trigger 3 fired but did not pass the actionability filter: apply_patch failed because of the one-off Windows process-logon error 1385, not an actionable skill defect.

## Evidence

Redline: `build/redline-verdict.json` reports GRAY, with `AGENTS.md` in gray, no boundary violations, and exit code 1 (review warning only). Workflow check passed clean. `git diff --check` passed.

## Result review

Completion criterion is satisfied. Scope remained limited to `AGENTS.md` and this Work Record; the material assumption remains valid, and final risk remains gray/Elevated.
