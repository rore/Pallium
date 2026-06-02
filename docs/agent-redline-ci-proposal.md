# agent-redline CI Proposal

**Status:** Applied. The workflow at [.github/workflows/agent-redline.yml](../.github/workflows/agent-redline.yml) is live on `main` in **push-driven mode**. This document is preserved for the original PR-driven shape (§1 below) and the rollout decisions (§4–§7) that still apply.

This bootstrap committed `agent-policy.yaml`, `[tool.importlinter]` rules in `pyproject.toml`, the local pre-push script, the PR template, and per-checkpoint docs in `docs/agent/`. **CI integration affects every push** and is left to a human decision.

## Why Pallium uses push-driven mode

The PR-driven shape in §1 is the agent-redline default. Pallium picked the push-driven shape (`on: push: branches: [main]`) instead because the actual flow is direct-to-main: 141 commits / 30 days, 2 PRs total. PR-shaped governance would only fire on ~1.4% of changes.

Trade-offs:
- **No sticky PR comment.** Verdict goes to the workflow log + an `agent-redline-verdict` artifact.
- **Enforce step fails CI on exit 1 OR exit 2** (not just exit 2). Without a PR comment, CI red is the only visibility channel for exit-1 warnings (gray zone, watch-list touched, unmet checkpoint in shadow, pr-size warn).
- **Calibration ran via the tuner's `--push-history` mode** rather than `--pr-dir`. Output: every red rule fires below 15%; tuner had no demotion suggestions.

The push-driven shape and tuner mode are documented in the agent-redline skill at `.claude/skills/agent-redline/extensions/python/scaffold.md` §5b.

## What this proposal covers

1. The PR-driven workflow shape (the framework default; not what Pallium uses)
2. CODEOWNERS additions
3. Branch-protection updates
4. The recommended initial mode (shadow)
5. The boundary-backend baseline question
6. Verifying locally
7. Decisions explicitly flagged for human judgment

## 1. PR-driven workflow shape (framework default — not what Pallium uses)

Pallium's live workflow uses the push-driven shape (see "Why Pallium uses push-driven mode" above and the workflow file directly). The PR-driven shape below is preserved as documentation for teams that operate through PRs.

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
        run: |
          mkdir -p build
          python scripts/run-import-linter.py --out build/import-linter-report.json
        # Exits 1 on violations; reporter step surfaces them. Drop this once
        # shadow window is done.
        continue-on-error: true
      - uses: actions/upload-artifact@v4
        with:
          name: boundary-report
          path: build/import-linter-report.json
          if-no-files-found: error

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

      - name: Run reporter
        id: report
        # Capture the reporter's exit code without failing the step yet —
        # the sticky comment must post regardless. The "Enforce reporter
        # exit code" step below translates exit 2 into a check failure.
        #
        # Reporter exit codes:
        #   0  clean (BLUE / no checkpoints / contracts pass)
        #   1  warnings (gray-zone / unmet checkpoint in shadow mode /
        #      watch-list touched / pr-size warn) — surfaces in comment,
        #      does NOT block CI
        #   2  binding-mode hard fail (boundary violation, unsatisfied
        #      checkpoint under binding, pr-size fail under binding) —
        #      blocks CI
        run: |
          set +e
          mkdir -p build
          git diff --name-only \
            "${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }}" \
            > build/changed-files.txt
          LINES_CHANGED=$(git diff --shortstat \
            "${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }}" \
            | awk '{for (i=1;i<=NF;i++) if ($i ~ /insertions?|deletions?/) s+=$(i-1)} END{print s+0}')
          python scripts/agent-redline-report.py \
            --policy agent-policy.yaml \
            --changed-files build/changed-files.txt \
            --lines-changed "${LINES_CHANGED:-0}" \
            --pr-labels "${{ join(github.event.pull_request.labels.*.name, ',') }}" \
            --json-out build/verdict.json \
            --comment-out build/comment.md
          EXIT=$?
          echo "exit_code=$EXIT" >> "$GITHUB_OUTPUT"
          echo "reporter exit code: $EXIT"

      - name: Post sticky PR comment
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          path: build/comment.md
          header: agent-redline

      - name: Upload verdict artifact
        uses: actions/upload-artifact@v4
        with:
          name: agent-redline-verdict
          path: |
            build/verdict.json
            build/comment.md

      - name: Enforce reporter exit code
        # Fail the report job (and thus the required check) only on exit 2.
        # Exit codes 0 and 1 leave the job green; the comment surfaces
        # warnings without blocking merge.
        run: |
          EXIT="${{ steps.report.outputs.exit_code }}"
          if [[ "$EXIT" == "2" ]]; then
            echo "Reporter exited 2 (binding-mode hard fail). Failing the report check."
            exit 1
          fi
          echo "Reporter exited $EXIT — non-blocking."
```

The reporter dispatches on `agent-policy.yaml`'s `boundaryAdapter:` block (declared `outputFormat: json-violations` + `outputPath: build/import-linter-report.json`) — no explicit `--boundary-format` flag needed.

The `set +e` + `EXIT=$?` capture is the canonical pattern from the agent-redline skill's `extensions/python/scaffold.md` §5. It's load-bearing: without it, `bash -e` propagates a non-zero reporter exit (exit 1 = warnings is the common case for non-blue PRs) and the sticky-comment step never runs — verdict computes but never reaches a human. The earlier `continue-on-error: true` workaround is no longer needed; the reporter's three-level exit code (0/1/2) is the explicit shadow-vs-binding signal.

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

The current workflow runs **on push to `main`**, so branch-protection-as-required-status-checks is moot for Pallium today (status checks gate PRs, but Pallium's flow is direct-push). If/when collaborators arrive and PRs become normal, switch the workflow to PR-driven (or list both triggers) and then add to required-status-checks:

- Settings → Branches → Branch protection rules for `main`
- Required status checks:
  - `test (ubuntu-latest, 3.12)` (existing)
  - `test (ubuntu-latest, 3.13)` (existing)
  - `test (windows-latest, 3.12)` (existing)
  - `test (windows-latest, 3.13)` (existing)
  - **`Boundary check (import-linter)` ← new**
  - **`agent-redline report` ← new**

For the soft-launch (shadow mode), do NOT add the new checks to required-status-checks yet. Watch the workflow log + verdict artifact for 4 weeks or 30 changesets, tune `agent-policy.yaml` based on what fires often, then promote to required.

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

1. **When to apply this workflow file.** **(Decided: applied; live in push-driven mode on `main`.)**
2. **PR-driven vs push-driven shape.** **(Decided: push-driven — see "Why Pallium uses push-driven mode" above.)** Switch to PR-driven (or list both triggers) when PRs become a normal part of the flow.
3. **CODEOWNERS handles.** Solo dev today; replace `TODO(owner):` with `@your-handle` when ready, or skip until collaborators exist.
4. **Whether to flip `modes.default: shadow → binding`.** The tuner's `--push-history --branch main --limit 30` run shows every red rule firing below 15% (no demotion suggestions). Calibration supports flipping. After the flip, drop `continue-on-error: true` from the boundary job in the same change — the reporter's exit-2 path catches boundary violations through `boundaryAdapter`, making the boundary job's `continue-on-error` redundant.
5. **Whether to baseline pre-existing violations.** Bootstrap analysis says contracts pass today (verified by every CI run since); no baselines needed beyond the one already in `pyproject.toml` for `storage.sqlite_workstream → capabilities.workstreams`.
6. **`storage.sqlite_workstream → capabilities.workstreams` follow-up refactor.** Move `WorkstreamStore` out of `capabilities/` (or out of `storage/`, depending on which side you want to own it) and drop the last baselined exception. Tracked in AGENTS.md "Known import-graph smells"; not bootstrap work.

## What still needs human action after applying this

- [x] Write `.github/workflows/agent-redline.yml` (live, push-driven shape)
- [ ] Decide on CODEOWNERS (§2) — skip or add with placeholders
- [ ] Decide on `modes.default: shadow → binding` flip (§7.4) — tuner says yes
- [ ] Replace placeholder owner handles when collaborators arrive
