# Update agent-workflow skill to latest version

<!-- agent-workflow:start -->
**Outcome:** The agent-workflow harness installed in Pallium is synced to the latest version from the local clone (`C:\Dev\rore\agent-workflow`, main @ 8730f7e), CI stays green, and the enforcement behavior is unchanged for consumers.

**Target:** rore/pallium — the installed agent-workflow footprint: `.claude/skills/agent-workflow/**`, vendored `scripts/{agent-workflow-check,format-verdict-comment,agent-redline-report,run-import-linter}.py`, `.claude/hooks/**`, `.claude/settings.json`, `.agent-redline/agent-policy.schema.json`, per-checkpoint doc mirrors `docs/agent-workflow/**` + `docs/agent-redline/skills/**`.

**Scope:** Overwrite the skill tree from `dist/agent-workflow/`; re-vendor the 4 vendored scripts (check, format-verdict, redline-report, **run-import-linter** — the last from `agent-redline/extensions/python/scripts/`); refresh `.claude/hooks/*` and merge `.claude/settings.json` + regenerate `.claude/hooks/guarded-paths.json` via the new `install-settings.py`; update the CI-consumed schema copy `.agent-redline/agent-policy.schema.json` from the new skill schema; refresh the doc mirrors `docs/agent-workflow/**` (7, ← `templates/checkpoints/*`) and `docs/agent-redline/skills/**` (8, ← `agent-redline/references/per-checkpoint/*`). NOT in scope: `.github/workflows/agent-workflow.yml` (live CI — unchanged, scripts CLI+output compatible), `agent-workflow.yaml`, `agent-redline-policy.yaml`, `AGENTS.md` (all verified already-current), `.agent-redline/suppressions.yaml` (local exemptions — must not be clobbered by the template).

**Constraints:** Do not change the live CI workflow (redline-RED, self-protected) — verified unnecessary. Preserve Pallium's `hooks.guardedPaths` in the regenerated settings. Do not alter `agent-workflow.yaml`/`agent-redline-policy.yaml` content. Keep the update mechanical (upstream content), no local edits to skill files.

**Completion criteria:** installed skill tree byte-matches `dist/agent-workflow/`; the 4 vendored scripts byte-match their dist sources; the two doc mirrors byte-match their skill sources; `settings.json`/`guarded-paths.json` still carry Pallium's guarded paths; `agent-redline-policy.yaml` validates against the updated schema; the new `agent-workflow-check.py` parses this Work Record cleanly; CI green (incl. `agent-workflow` + `redline` gates running the new scripts).

**Risk:** Elevated

**Complexity:** Moderate

**Reason:** Changed paths are gray (`.agent-redline/`, `.claude/hooks/`, `.claude/settings.json`, this Work Record) → Elevated; `scripts/**` is blue and `.claude/skills/**` is suppressed. No red-zone path touched (the redline-RED `.github/workflows/agent-workflow.yml` is deliberately left unchanged). Moderate: many files across skill tree + scripts + hooks + schema, with reconciliation and verification, though one coherent session.

**Discovery:** Clone on latest main @ 8730f7e (#4 "CodeRabbit harness defects A–H"). `diff -rq` shows every file in the installed skill tree differs in content, same file set (no adds/removes); all 3 vendored scripts differ. The 3 scripts' CLI invocations are byte-identical between old and new CI templates → new scripts are drop-in compatible, so the live `agent-workflow.yml` needs no change. Pallium's `agent-workflow.yaml` validates against the new config schema; `agent-redline-policy.yaml` validates against the new agent-policy schema; the AGENTS.md agents-section body is identical to the new template. `.agent-redline/agent-policy.schema.json` is a verified copy of the installed skill schema.

**Material assumptions:**
- New scripts are CLI-compatible with the live workflow. Disproved by: CI step erroring on an arg → action: reconcile the live `agent-workflow.yml` (would raise risk to red-zone touch).
- `install-settings.py` regenerates settings from `agent-workflow.yaml`'s `hooks.guardedPaths`. Disproved by: regenerated `guarded-paths.json` missing Pallium's paths → action: restore paths / pin the file.

**Plan:** (1) `cp -r dist/agent-workflow/* .claude/skills/agent-workflow/` (overwrite; file set identical). (2) Copy the 4 vendored scripts from their dist locations (3 from `dist/agent-workflow/scripts/` + `run-import-linter.py` from `dist/agent-workflow/agent-redline/extensions/python/scripts/`). (3) Copy `.claude/hooks/*` from dist hooks; run `install-settings.py` (create-or-merge, idempotent) to merge `settings.json` + regenerate `guarded-paths.json`; diff to confirm guarded paths preserved. (4) Copy the new skill `agent-redline/assets/schema/agent-policy.schema.json` → `.agent-redline/agent-policy.schema.json`; validate `agent-redline-policy.yaml`. (5) Refresh doc mirrors: `templates/checkpoints/*` → `docs/agent-workflow/*`; `agent-redline/references/per-checkpoint/*` → `docs/agent-redline/skills/*`. (6) Confirm no diff in `agent-workflow.yaml`, `agent-redline-policy.yaml`, `AGENTS.md`, `.agent-redline/suppressions.yaml`. Stop condition: any script/schema validation failure → pause, do not push.

**Verification plan:** Local — `diff -rq` installed tree vs dist = clean; 4 scripts byte-match; both doc mirrors byte-match their skill sources; `guarded-paths.json` contains Pallium's 9 package prefixes; `jsonschema.validate(policy, new schema)` passes; run the new `agent-workflow-check.py --slug update-agent-workflow` → shape/field predicates pass. CI — on the PR, `agent-workflow` + `redline` + `test` + `windows-smoke` green (the gates now execute the new vendored scripts, incl. `run-import-linter.py`).

**Plan review:** clean-context Explore subagent — verdict *sound-with-nits*; full prose under `## Plan review` below. Three nits applied: added `scripts/run-import-linter.py` (4th vendored script the live CI calls) and the two per-checkpoint doc mirrors to scope; confirmed `.agent-redline/suppressions.yaml` + live workflow + config-regen correctly left as-is.

**Approvals:** Not required at this risk level (Elevated).

**Exceptions:** —

**State:** Ready for review
<!-- agent-workflow:end -->

## Plan review

Clean-context review (Explore subagent, read-only) of the plan + full installed footprint. **Verdict: sound-with-nits** — core sync mechanics safe; scope had two completeness gaps + a mis-count, all folded in:

- **`scripts/run-import-linter.py`** (from `agent-redline/extensions/python/scripts/`) is a 4th vendored script the live `redline` job calls (`agent-workflow.yml:57`); installed copy differs from dist → added to scope. (Low CI-break risk — argparse surface byte-identical — but a real divergence.)
- **`docs/agent-workflow/**` (7) + `docs/agent-redline/skills/**` (8)** are bootstrap-installed mirrors of skill content; all 15 differ from dist → added to scope (docs are blue).
- **Untouched decisions confirmed sound:** leaving `.github/workflows/agent-workflow.yml` (verified: all 4 scripts' CLI args byte-identical; reporter still emits `verdict`/`summary`/`zones`/`boundaryViolations` that the workflow parses inline); `install-settings.py` is create-or-merge/idempotent (won't drop Pallium's hooks or the 9 guarded prefixes); `.agent-redline/suppressions.yaml` is local exemptions and must not be clobbered by the template.
- **Verification added:** doc-mirror + `run-import-linter.py` parity `diff` checks.

## Implementation

Synced from `C:\Dev\rore\agent-workflow` (main @ 8730f7e). Mechanical, upstream content only:
- Overwrote `.claude/skills/agent-workflow/` from `dist/agent-workflow/`.
- Re-vendored 4 scripts: `agent-workflow-check.py`, `format-verdict-comment.py`, `agent-redline-report.py`, `run-import-linter.py`.
- Refreshed `.claude/hooks/*`; ran `install-settings.py` (reported "already installed, no change"; regenerated `guarded-paths.json` with the 9 prefixes).
- Copied new `agent-policy.schema.json` → `.agent-redline/agent-policy.schema.json`.
- Refreshed doc mirrors: `docs/agent-workflow/*` (7), `docs/agent-redline/skills/*` (8).
- Left untouched (verified current): `.github/workflows/agent-workflow.yml`, `agent-workflow.yaml`, `agent-redline-policy.yaml`, `AGENTS.md`, `.agent-redline/suppressions.yaml`.

## Evidence (local verification)

- `diff -rq .claude/skills/agent-workflow dist/agent-workflow` → clean (byte-identical tree).
- All 4 vendored scripts byte-match their dist sources; both doc mirrors (15 files) byte-match skill sources.
- `settings.json` unchanged; `guarded-paths.json` = the 9 Pallium prefixes.
- `agent-redline-policy.yaml` VALID against the updated `.agent-redline/agent-policy.schema.json`; `agent-workflow.yaml` VALID against the new config schema.
- New `agent-workflow-check.py --slug update-agent-workflow`: all shape/field/state/approval predicates PASS (incl. `approval.elevated_clean_context_review_present`). Only `risk.redline_findings_available` fails locally — expected (no CI verdict), passes in CI.
- Definitive gate = PR CI running the new vendored scripts (`agent-workflow` + `redline` + `test` + `windows-smoke`).
