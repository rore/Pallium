# Bootstrap: install agent-workflow on Pallium

<!-- agent-workflow:start -->
**Outcome:** agent-workflow installed and operational on Pallium; Work Records drive all future engineering tasks; CI gates enforce the harness on PRs.

**Target:** rore/pallium, branch `install-agent-workflow`

**Scope:** `.claude/skills/agent-workflow/` (already committed), `agent-workflow.yaml`, updated `agent-policy.yaml` (adopt + one path fix for the new CI workflow name), vendored `scripts/agent-workflow-check.py` + `scripts/agent-redline-report.py` + `scripts/format-verdict-comment.py`, Claude Code hooks under `.claude/hooks/`, AGENTS.md agents-section update, per-checkpoint docs at `docs/agent/`, `.agent-workflow/tasks/README.md`, optional `.github/workflows/agent-workflow.yml` (Phase 5 confirmation required).

**Constraints:** Never overwrite existing `agent-workflow.yaml` without explicit confirmation (none exists — proceed). Never overwrite `agent-policy.yaml` (exists — adopt as-is, one path update). Never modify AGENTS.md content outside the marker block. Never write CI workflow outside Phase 5.

**Completion criteria:** Phase 6 self-summary written; backend probe passes; `.claude/skills/agent-workflow/SKILL.md` exists; policy schema-validates; manifest check passes.

**Risk:** Elevated

**Complexity:** Simple

**Reason:** Bootstrap installs CI gates and AGENTS.md — default profile §3 Elevated. Existing redline policy shortens the path (adoption, not fresh creation).

**Discovery:**
- Skill installed at `.claude/skills/agent-workflow/` (untracked, awaiting Phase 4 commit).
- Standalone agent-redline skill, CI workflow, and scripts removed (staged).
- Existing redline policy at `agent-policy.yaml` (note: filename uses repo convention, not the default `agent-redline-policy.yaml` — adopting in place; one path fix needed: line 72 references the removed `.github/workflows/agent-redline.yml`).
- AGENTS.md has existing agent-redline section with marker-free prose — will be replaced with marker-wrapped agents-section in Phase 4.
- Per-checkpoint docs already at `docs/agent/` (not the default `docs/agent-workflow/`) — bootstrap will refresh in place.
- CI uses PR + push triggers. 4 merged PRs — tuner threshold not met, skipped.
- Import-linter configured in `pyproject.toml`, boundary adapter writes to `build/import-linter-report.json`. Python extension applies.
- No CODEOWNERS, no pre-push hook.

**Material assumptions:**
- `agent-policy.yaml` (not `agent-redline-policy.yaml`) is the repo convention for the policy filename; the CI workflow template will reference it by the configured path. Evidence that disproves: CI template only accepts a hardcoded `agent-redline-policy.yaml` name → action: rename the file.
- Developer wants per-checkpoint docs refreshed in `docs/agent/` (existing location), not moved to `docs/agent-workflow/`. Evidence that disproves: explicit instruction → action: copy to `docs/agent-workflow/` instead.

**Plan:** Walk bootstrap's six phases per `bootstrap-mode.md`. Phase 1 done (this record). Phase 2 propose drafts. Phase 3 adapt with sign-off. Phase 4 write committed artifacts. Phase 5 confirm CI. Phase 6 self-summary + probe.

**Verification plan:** Phase 6 backend probe (`python scripts/agent-workflow-check.py --repo-root . --slug _probe`). Manifest check against `.claude/skills/agent-workflow/manifest.txt`. Policy schema validation against bundled schema. Post-PR CI green (once workflow is installed).

**Plan review:** self (Elevated → clean-context agent review sufficient; no high-risk trigger)

**Approvals:** Not required at this risk level

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->
