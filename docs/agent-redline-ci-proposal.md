# agent-redline CI Proposal

**Status:** proposal — NOT applied automatically. Review with whoever owns CI, apply when ready.

This bootstrap committed `agent-policy.yaml`, `[tool.importlinter]` rules in `pyproject.toml`, the local pre-push script, the PR template, and per-checkpoint docs in `docs/agent/`. **CI integration affects every push** and is left to a human decision.

## What this proposal covers

1. A new `.github/workflows/agent-redline.yml` workflow
2. CODEOWNERS additions
3. Branch-protection updates
4. The recommended initial mode (shadow)
5. The boundary-backend baseline question

## 1. Proposed workflow file

Write this to `.github/workflows/agent-redline.yml` when ready to apply:

```yaml
name: agent-redline

on:
  pull_request:
    branches: [main]

jobs:
  boundary:
    name: Boundary check (import-linter)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install package + dev deps (incl. import-linter)
        run: pip install -e ".[dev]"
      - name: Run import-linter via adapter
        run: python scripts/run-import-linter.py --out build/import-linter-report.json
        # Exits 1 on violations; CI continues so the reporter step can surface them.
        continue-on-error: true
      - uses: actions/upload-artifact@v4
        with:
          name: boundary-report
          path: build/import-linter-report.json

  report:
    name: agent-redline report
    needs: boundary
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/download-artifact@v4
        with:
          name: boundary-report
          path: build/
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pyyaml jsonschema
      - name: Run agent-redline reporter
        run: |
          mkdir -p build
          git diff --name-only \
            ${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }} \
            > build/changed-files.txt
          python scripts/agent-redline-report.py \
            --policy agent-policy.yaml \
            --changed-files build/changed-files.txt \
            --pr-labels "$(jq -r '.pull_request.labels[].name' "$GITHUB_EVENT_PATH" | paste -sd,)" \
            --json-out build/verdict.json \
            --comment-out build/comment.md
      - name: Post / update PR comment
        # The reporter writes build/comment.md; post it via marocchino or
        # peter-evans/create-or-update-comment to keep one sticky comment.
        # Implementation left to whoever applies this workflow.
        run: cat build/comment.md
```

The reporter dispatches on `agent-policy.yaml`'s `boundaryAdapter:` block (declared `outputFormat: json-violations` + `outputPath: build/import-linter-report.json`) — no explicit `--boundary-format` flag needed.

## 2. CODEOWNERS additions

There's no `CODEOWNERS` today and you're solo dev, so this is mostly a forward-compat placeholder. Drop this at `.github/CODEOWNERS` when you have collaborators or want explicit checkpoint ownership:

```
# .github/CODEOWNERS
# Replace placeholders with actual @username or @org/team handles.

# Architecture review — boundary contracts and structural code
agent-policy.yaml                     # TODO(owner): @your-handle
pyproject.toml                        # TODO(owner): @your-handle
core/contracts.py                     # TODO(owner): @your-handle
core/models.py                        # TODO(owner): @your-handle
core/service.py                       # TODO(owner): @your-handle
core/routing.py                       # TODO(owner): @your-handle
storage/sqlite_workstream.py          # TODO(owner): @your-handle

# API review
api/routes.py                         # TODO(owner): @your-handle
api/schemas.py                        # TODO(owner): @your-handle

# Persistence review
storage/sqlite_schema.py              # TODO(owner): @your-handle
storage/sqlite_codec.py               # TODO(owner): @your-handle

# Security review
core/visibility.py                    # TODO(owner): @your-handle
```

Until owners exist, checkpoint satisfaction falls back to the labels declared in `agent-policy.yaml` (`architecture-reviewed`, `api-reviewed`, `persistence-reviewed`, `security-reviewed`).

## 3. Branch protection

When you flip the workflow on, update `main` branch protection to include the new check as required:

- Settings → Branches → Branch protection rules for `main`
- Required status checks:
  - `test (ubuntu-latest, 3.12)` (existing)
  - `test (ubuntu-latest, 3.13)` (existing)
  - `test (windows-latest, 3.12)` (existing)
  - `test (windows-latest, 3.13)` (existing)
  - **`Boundary check (import-linter)` ← new**
  - **`agent-redline report` ← new**

For the soft-launch (shadow mode), do NOT add the new checks to required-status-checks yet. Watch the PR comments / job results for 4 weeks or 30 PRs, tune `agent-policy.yaml` based on what fires often, then promote to required.

## 4. Recommended initial mode: shadow

`agent-policy.yaml` ships with:

```yaml
modes:
  default: shadow
  perCheck:
    boundary_violation: binding
```

Rationale:

- **Shadow for everything except boundary violations** — zones, PR-size, checkpoints, etc. are calibrated against this codebase's actual PR history (which is currently 0 merged PRs — calibration completes during Window 1). Shadow surfaces them in the PR comment without failing.
- **Binding for `boundary_violation` from day one** — the `[tool.importlinter]` contracts encode rules that pass today (verified during bootstrap). A new violation is a real regression, not a calibration question.

After the initial Window (4 weeks or 30 PRs, whichever is later):
1. Review red-zone fire rates. Demote any path that fires on routine feature PRs to `watch:` or `blue:`.
2. Flip `modes.default` to `binding`.
3. Add the workflow checks to required-status-checks.

## 5. Boundary-backend baseline

Before flipping `import-linter` to enforcement, run it once on `main`:

```bash
python scripts/run-import-linter.py --out /tmp/baseline.json
```

If contracts pass — no baseline needed; the `ignore_imports` lines for the two known smells (`storage.sqlite -> app.transient_errors`, `storage.sqlite_workstream -> capabilities.workstreams`) already cover the today-state.

If contracts fail (unexpected — bootstrap analysis says they shouldn't):

- **Few violations (<10):** add them to the relevant contract's `ignore_imports` and document each in AGENTS.md's smells block.
- **Many violations:** flip `modes.perCheck.boundary_violation` to `shadow` until paid down.

Either way, do NOT silently start failing CI on pre-existing violations.

## 6. Verifying locally before applying CI

```bash
# Install dev deps (pulls import-linter)
pip install -e ".[dev]"

# Validate the policy parses against the schema
python -c "import json, yaml, jsonschema; \
  s = json.load(open('.claude/skills/agent-redline/assets/schema/agent-policy.schema.json')); \
  p = yaml.safe_load(open('agent-policy.yaml')); \
  jsonschema.validate(p, s); print('policy OK')"

# Run import-linter against current main
python scripts/run-import-linter.py --out build/import-linter-report.json

# Run the local agent-redline pre-push check (boundary + reporter end-to-end)
bash scripts/agent-redline-check.sh
```

The pre-push check runs the import-linter adapter automatically when it's present (Pallium has it), then invokes the vendored reporter at `scripts/agent-redline-report.py`. Both ship with this bootstrap.

## 7. Decisions explicitly flagged for human judgment

These were not decided automatically — pick when you're ready:

1. **When to apply this workflow file.** Now, in a soft-launch branch, or after watching shadow-mode signal for a Window?
2. **CODEOWNERS handles.** Solo dev today; replace `TODO(owner):` with `@your-handle` when ready, or skip until collaborators exist.
3. **Whether to drop `continue-on-error: true` on the boundary job.** Keep it during shadow; drop it to make import-linter violations fail PRs.
4. **Whether to baseline pre-existing violations.** Bootstrap analysis says contracts pass today; verify with `python scripts/run-import-linter.py` before flipping.
5. **`storage.sqlite → app.transient_errors` follow-up refactor.** Move `transient_errors` to `core/errors.py` and drop the baselined exception. Tracked in AGENTS.md "Known import-graph smells"; not bootstrap work.

## What still needs human action after applying this

- [ ] Write `.github/workflows/agent-redline.yml` (copy from §1 above)
- [ ] Decide on CODEOWNERS (§2) — skip or add with placeholders
- [ ] Update branch protection on `main` (§3) — only after Window
- [ ] Run shadow mode for 4 weeks / 30 PRs (§4)
- [ ] Validate boundary baseline on `main` (§5)
- [ ] Replace placeholder owner handles when collaborators arrive
