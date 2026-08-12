# agent-workflow CI proposal

Workflow file installed on 2026-08-12. Branch protection and CODEOWNERS additions still need human action.

## Installed

- `.github/workflows/agent-workflow.yml` — combined redline + compliance CI. Installed directly (developer confirmed).

## Adaptations from template

- `runs-on: ubuntu-latest` (template default `self-hosted` is not applicable here)
- `python-version: '3.12'` to match Pallium's minimum
- Import-linter run step added before the reporter (`scripts/run-import-linter.py --out build/import-linter-report.json`); `BOUNDARY_ARG` updated to reference `build/import-linter-report.json` with `--boundary-format json-violations` (matching `boundaryAdapter` config in `agent-redline-policy.yaml`)
- `pip install -e "." import-linter pyyaml jsonschema` in the `redline` job so import-linter can resolve Pallium's packages

## Still needs human action

### Required-status-checks for branch protection

Add these two job names as required status checks on the `main` branch protection rule:

- `redline`
- `agent-workflow`

Use the bare job names — not `agent-workflow / redline` (display-only prefix).

### Require conversation resolution

Enable `required_conversation_resolution` on the `main` branch-protection rule so GitHub refuses merge while any review thread is unresolved.

### CODEOWNERS

No CODEOWNERS file exists. Tuner skipped (4 merged PRs < 10 threshold). Recommended structure when the team grows:

```
# Default reviewer for all paths
*                        @TODO-codeowners-team

# Self-protecting governance paths
agent-redline-policy.yaml  @TODO-codeowners-team
agent-workflow.yaml        @TODO-codeowners-team
```

### Recommended initial mode for redline

Already set to `shadow` in `agent-redline-policy.yaml` (`modes.default: shadow`). Run in shadow for 4 weeks / 30 PRs, then flip `modes.default: binding` once the fire-rate is tuned.
