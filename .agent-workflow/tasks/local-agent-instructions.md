<!-- agent-workflow:start -->
**Outcome:** Pallium's machine-specific installation guidance lives in an ignored repository-local file instead of global agent context, while installed agents are directed to read it when present.

**Target:** Pallium repository instruction chain.

**Scope:** Add a generic optional-local-instructions pointer to tracked `AGENTS.md`; create ignored `AGENTS.local.md`; update `.git/info/exclude`; remove the marked installation block from personal Codex and Claude instruction files.

**Constraints:** Keep all shared Pallium guidance, including derived-memory guidance, unchanged. Do not commit machine-specific paths. Preserve unrelated working-tree files.

**Completion criteria:** `AGENTS.local.md` is ignored and contains the installation guidance; tracked `AGENTS.md` directs agents to it; personal global files no longer contain the installation block; tracked scope contains only the pointer and this Work Record.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Redline classifies `AGENTS.md` as gray because it is governance and outside the documentation exemption; there are no boundary, runtime, security, persistence, or API surfaces.

**Discovery:** Codex loads at most one instruction file per directory, so root `AGENTS.override.md` would hide tracked `AGENTS.md`. Repository `CLAUDE.md` already requires Claude to read `AGENTS.md`; OpenCode also reads `AGENTS.md`. `.git/info/exclude` provides a machine-only ignore rule.

**Material assumptions:** Agents follow an explicit `AGENTS.md` instruction to read `AGENTS.local.md` when present; a fresh-agent failure to load it would disprove this and require host-native configuration instead.

**Plan:** Validate that both personal files contain exactly one identical, well-ordered installation marker block and snapshot their content outside it. Copy that block to repository-root `AGENTS.local.md`; resolve the checkout's exclude path and append root-anchored `/AGENTS.local.md`; add one supplemental-file pointer near the top of tracked `AGENTS.md`; then remove only the marked personal blocks. Stop on missing, duplicate, mismatched, or conflicting content. Verify Git state, unchanged surrounding global guidance, workflow checks, and fresh discovery in each available agent host.

**Verification plan:** Local instruction migration and discovery chain remain correct → `git check-ignore -v`, empty `git ls-files -- AGENTS.local.md`, exact outside-block hashes, marker/pointer/content assertions, `git diff --check`, final diff inspection, workflow checker, and fresh-host probes where permitted; record blocked hosts as unverified.

**Plan review:** Clean-context review by `/root/review_local_agent_plan`; required safety and fresh-discovery checks incorporated in the revised Plan and Verification plan. See `## Plan review`.

**Approvals:** Not required at this risk level.

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Implementation

- Discovery confirmed the tracked pointer is required for a reliable repository-local pattern; native override files would mask shared instructions.
- Redline pre-edit verdict: gray path, no boundary or surface findings; Elevated/Simple.
- Clean-context plan-review findings were incorporated before implementation.
- Migrated the exact marked block, added the root-anchored local exclude and supplemental pointer, and removed only the marked global copies.

## Evidence

- `git check-ignore -v -- AGENTS.local.md` resolves to `.git/info/exclude:18:/AGENTS.local.md`; `git ls-files -- AGENTS.local.md` is empty.
- Exact post-removal hashes match the pre-removal outside-block hashes for both personal instruction files. Both retain the Pallium and Derived memory sections, and neither retains the installation marker.
- The local file matches the migrated block, the tracked pointer is supplemental, `CLAUDE.md` still requires `AGENTS.md`, and OpenCode's project instruction file remains `AGENTS.md`.
- `git diff --check` passed. Fresh Codex/Claude/OpenCode model probes are unverified because host safety policy rejected transmitting repository instructions and the machine-local path.
- `.venv\Scripts\python.exe scripts/agent-workflow-check.py --repo-root . --slug local-agent-instructions` passed clean.

## Result review

Pass for the scoped instruction migration, with a disclosed verification limitation. The inspected tracked diff adds only the supplemental repository-root pointer; the Work Record is the only other task file. The local installation block is present, ignored by the root-anchored exclude rule, and untracked. Recorded exact outside-block hash checks support preservation of personal guidance; those historical comparisons were not independently repeated by this reviewer.

Verification is adequate for file relocation and tracked scope: ignore/tracking checks were independently confirmed, and content assertions, diff checks, and the workflow checker are recorded as passing. Fresh Codex/Claude/OpenCode model probes remain unverified because host safety policy rejected them. Thus the material assumption that each fresh host follows the pointer remains unresolved; this review does not certify end-to-end discovery or override that rejection.

No scope expansion or new runtime/API/persistence/security boundary appears; final classification remains Elevated/Simple. The unrelated untracked `scripts/validate_relay_cutover_copies.py` remains present and was not modified. No product or roadmap status changed. The previously recorded `CLAUDE.md` workflow-reference drift remains outside scope. No skill-feedback trigger arose during this review.

## Plan review

Clean-context review: changes required before implementation. The optional pointer is a suitably small additive design; `CLAUDE.md` already requires `AGENTS.md`, and avoiding `AGENTS.override.md` preserves the shared instruction chain. This review does not establish installed Codex/OpenCode loading behavior from the assertion in Discovery alone.

- Required: verify discovery in fresh Codex, Claude, and OpenCode sessions, asking each to identify both the shared instructions and the local installation guidance without supplying its contents. Record unavailable hosts as unverified; file-presence checks alone do not discharge the explicit fresh-agent assumption. Confirm the pointer names the repository-root file and treats it as supplemental guidance.
- Required: enumerate the exact personal instruction targets in local execution notes; require exactly one well-ordered marker pair per source, compare the source blocks, and preserve all text outside those blocks. Verify the local copy matches the intended installation guidance before removing either source. Missing, mismatched, or duplicate markers and an existing conflicting destination must stop the migration.
- Required: resolve the exclude location with `git rev-parse --git-path info/exclude`, append a root-anchored `/AGENTS.local.md` rule without replacing existing rules, and verify both `git check-ignore -v -- AGENTS.local.md` and an empty `git ls-files -- AGENTS.local.md`. Ignore rules do not protect an already tracked file. Scope this guarantee to the checkout containing the local file; another worktree does not acquire its contents automatically.
- Required: check the final tracked diff against the pre-edit baseline and compare each global file outside its removed block, so unchanged shared/derived-memory guidance is demonstrated. The existing unrelated untracked `scripts/validate_relay_cutover_copies.py` must remain untouched. Run the workflow checker; runtime test suites add no useful coverage for this instruction-only change.

No roadmap change is indicated because this relocates local operating guidance without changing product capability. Existing `CLAUDE.md` references to `agent-policy.yaml` and `docs/agent/` differ from the current workflow names; that drift is outside this task and should not be silently repaired here.



