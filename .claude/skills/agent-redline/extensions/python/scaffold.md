# python — scaffold

What bootstrap generates and how. Each section maps to one artifact.

By the time you reach this scaffold, `bootstrap-mode.md` Phase 3b has already tuned the policy against the repo's PR history (or noted that history was thin). Do not re-run the tuner here.

**Before generating any of this:** check whether the repo already has an `import-linter` configuration (look for `[tool.importlinter]` in `pyproject.toml`, a `.importlinter` file, or `[importlinter]` in `setup.cfg`). If found:

- Do NOT generate new contracts.
- Translate the existing contracts into `boundaries:` entries in the policy. The policy's `boundaries:` are metadata the reporter surfaces; the existing contracts do the real enforcement.
- Skip §1 (dependency may already be there) and §2 (contracts exist).
- §3, §4, §5, §6 still apply — the existing contracts still produce a report the reporter reads, and CI / API handling is independent.
- Tell the developer: existing contracts stay authoritative; the policy mirrors them so the agent and reporter understand them.

## 1. import-linter dependency

Add `import-linter` to the dev/test dependency group. Pin to a known stable major version range — the adapter script (§4) calls internal modules and is verified against `>=2.0,<3`.

**`pyproject.toml` (PEP 621):**
```toml
[project.optional-dependencies]
dev = [
    "import-linter>=2.0,<3",
    # ... existing dev deps
]
```

**`pyproject.toml` (Poetry):**
```toml
[tool.poetry.group.dev.dependencies]
import-linter = ">=2.0,<3"
```

**`requirements-dev.txt` (or wherever dev deps live):**
```
import-linter>=2.0,<3
```

If the project is installed editable in CI (`pip install -e '.[dev]'`), no further wiring is needed. import-linter will discover the package by name.

## 2. import-linter contracts

Generate one contract per `boundaries[]` entry in the policy. Use the contract types from `profile.md` for the chosen shape.

**Configuration location.** Prefer `pyproject.toml` (`[tool.importlinter]` block) — that's where most modern tooling lives. Fall back to `.importlinter` (INI) if the repo already has one or has a strong preference.

**Configuration in `pyproject.toml`:**
```toml
[tool.importlinter]
root_package = "<pkg>"            # the actual package name from inspection
exclude_type_checking_imports = true
# Set this when any forbidden_modules entry points at an external
# package (e.g. fastapi, sqlalchemy). Without it, import-linter refuses
# to run such contracts.
include_external_packages = true

# import-linter layers go HIGH -> LOW. Higher layers (listed first) may import
# lower ones; lower layers may not import higher.
[[tool.importlinter.contracts]]
name = "Layered architecture"
type = "layers"
layers = [
    "<pkg>.api",
    "<pkg>.application",
    "<pkg>.domain",
]
```

(See `profile.md` for the full set of default contracts per shape and the Django addendum.)

**Substitute placeholders:**
- `<pkg>` → actual top-level package name (read from `pyproject.toml`'s `[project] name` or `[tool.setuptools] packages` or layout inspection).
- For src-layout, `root_package` is still just the package name — `import-linter` resolves it from the `sys.path`-installable install.
- Layer modules below `<pkg>` must exist as packages (with `__init__.py`). If a layered module is missing, `import-linter` fails the contract — bootstrap should either skip that layer entry or note the missing layer.

**Wrap optional layers in parentheses** so the contract doesn't fail when a layer is genuinely absent:
```toml
layers = [
    "<pkg>.api",
    "<pkg>.application",
    "(<pkg>.domain)",       # optional; contract passes if missing
]
```

**Multi-package layout** (each layer is its own top-level package, no parent — see `profile.md` "Layout variants"). Use `root_packages` (plural) and top-level layer names:

```toml
[tool.importlinter]
root_packages = ["api", "core", "storage"]    # one entry per top-level package layer
exclude_type_checking_imports = true
include_external_packages = true

# Use `forbidden` between layer pairs instead of a single linear `layers` list.
# Set `allow_indirect_imports = true` (see profile.md "multi-package" note).
[[tool.importlinter.contracts]]
name = "core stays independent of higher layers"
type = "forbidden"
source_modules = ["core"]
forbidden_modules = ["api", "storage"]
allow_indirect_imports = true
```

Bootstrap derives the layer order from the repo's architecture docs (`docs/`, `AGENTS.md`) when present; ask the developer when not. Generate one `forbidden` contract per illegal direction.

## 3. The adapter script

Bootstrap copies `extensions/python/scripts/run-import-linter.py` into the consuming repo at `scripts/run-import-linter.py`. The script runs `import-linter` and emits `boundary-violations.json` (matching `core/schema/boundary-violations.schema.json`).

Why a separate script: `import-linter`'s CLI emits Rich-rendered text only (no `--format json`). The adapter calls the internal `create_report(...)` API and walks the report.

The script is self-contained — no further integration needed. CI invokes it (§4), the reporter reads its output (§5).

## 4. CI snippet

Two flow modes — bootstrap-mode.md Phase 1 elicits which one applies:

- **PR-driven flow** — pull requests are the unit of review; the verdict surfaces via a sticky PR comment. Use `on: pull_request:`.
- **Push-driven flow** — solo or trunk-based; commits go straight to a long-lived branch. No PR, so the verdict surfaces via the CI run + a JSON artifact. Use `on: push:`.

Both modes share the boundary job. They differ only in trigger, in how changed-files is computed, and in how the report job surfaces the verdict.

### Boundary job (same for both modes)

Add to the CI proposal:

```yaml
boundary:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: '3.11'                # match the repo's Python version
        cache: 'pip'
    - run: pip install -e '.[dev]'            # editable; import-linter discovers <pkg>
    - run: python scripts/run-import-linter.py --out build/import-linter-report.json
      # The script exits 1 on violations; CI continues so the reporter can surface them.
      continue-on-error: true
    - uses: actions/upload-artifact@v4
      with:
        name: boundary-report
        path: build/import-linter-report.json
```

For `pip-tools` / `requirements-dev.txt` repos, replace the install step:
```yaml
    - run: pip install -r requirements-dev.txt && pip install -e .
```

For Poetry repos:
```yaml
    - run: |
        pip install poetry
        poetry install --with dev
    - run: poetry run python scripts/run-import-linter.py --out build/import-linter-report.json
```

## 5. Reporter wiring

The reporter reads `build/import-linter-report.json` because the policy declares it via `boundaryAdapter`:

```yaml
boundaryAdapter:
  outputFormat: json-violations
  outputPath: build/import-linter-report.json
```

The reporter dispatches on `outputFormat` automatically when no explicit `--boundary-format` flag is passed. Two flow modes follow.

### 5a. PR-driven flow — `on: pull_request:`

```yaml
on:
  pull_request:
    branches: [main]

permissions:
  contents: read
  pull-requests: write   # required for the sticky comment

jobs:
  # boundary: ... (see §4)
  report:
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
          python-version: '3.11'
      - run: pip install pyyaml jsonschema

      - name: Run reporter
        id: report
        # Capture the reporter's exit code without failing the step yet —
        # we want the sticky comment to post regardless. The "Enforce
        # reporter exit code" step below translates exit code 2
        # (binding-mode hard fail) into a step failure.
        #
        # Reporter exit codes:
        #   0  clean (BLUE / no checkpoints / contracts pass)
        #   1  warnings (gray-zone / unmet checkpoint in shadow mode /
        #      watch-list touched / pr-size warn) — surfaces in the comment,
        #      does NOT block CI
        #   2  binding-mode hard fail (boundary violation, unsatisfied
        #      checkpoint under binding, pr-size fail under binding) —
        #      blocks CI
        #
        # Without the `set +e` + capture pattern, bash's default `-e` mode
        # makes ANY non-zero reporter exit fail the step. The comment
        # action and the enforce step never run, the verdict computes but
        # never reaches a human, and shadow mode's "surface, don't block"
        # contract silently breaks.
        run: |
          set +e
          mkdir -p build
          git diff --name-only \
            ${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }} \
            > build/changed-files.txt
          # `--numstat` so the reporter can apply policy.excludes to the
          # size budget. Without this, excludes affect zone classification
          # but NOT prSize, which silently double-counts generated /
          # vendored / excluded files in the line budget.
          git diff --numstat \
            ${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }} \
            > build/lines-per-file.txt
          LABELS="$(jq -r '.pull_request.labels[].name' "$GITHUB_EVENT_PATH" | paste -sd,)"
          python scripts/agent-redline-report.py \
            --policy agent-policy.yaml \
            --changed-files build/changed-files.txt \
            --lines-per-file build/lines-per-file.txt \
            --pr-labels "$LABELS" \
            --json-out build/verdict.json \
            --comment-out build/comment.md
          EXIT=$?
          echo "exit_code=$EXIT" >> "$GITHUB_OUTPUT"
          echo "--- verdict.json ---" && cat build/verdict.json
          echo "--- comment.md ---" && cat build/comment.md
          echo "reporter exit code: $EXIT"

      - name: Post sticky PR comment
        uses: marocchino/sticky-pull-request-comment@v2
        with:
          path: build/comment.md
          header: agent-redline

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

### 5b. Push-driven flow — `on: push:`

For solo developers and trunk-based teams. No PR comment surface, so the verdict surfaces via the run-page summary; the workflow itself fails on `EXIT != 0` (both RED warnings and BOUNDARY_VIOLATION hard fails) so GitHub's default email-on-failure notification fires for the user who triggered the run.

**The agent-redline workflow is its own file in `.github/workflows/`. It runs independently of the repo's other CI workflows (tests, builds, linters). A red agent-redline run does not fail those workflows; it produces an independent red badge + email. Branch protection (if used) can require agent-redline to be green for merge, or treat it as informational, per repo policy.**

```yaml
on:
  push:
    branches: [main]   # adjust to the long-lived branch(es) you push to

permissions:
  contents: read

jobs:
  # boundary: ... (see §4)
  report:
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
          python-version: '3.11'
      - run: pip install pyyaml jsonschema

      - name: Run reporter
        id: report
        # Same exit-code contract as PR mode (0/1/2). See PR-mode comment
        # block for full description.
        #
        # Push-mode-specific:
        # - BEFORE/AFTER diff handles "first push to a branch" (BEFORE
        #   is all-zeros) and force-push (BEFORE may be a SHA the runner
        #   doesn't have) by falling back to merge-base against the
        #   default branch.
        # - --flow-mode push tells the reporter to render checkpoint
        #   satisfier text as a review obligation on the commit, NOT as
        #   "Satisfy by: CODEOWNER approval or label X" (neither
        #   mechanism exists on a direct push).
        run: |
          set +e
          mkdir -p build
          BEFORE="${{ github.event.before }}"
          AFTER="${{ github.sha }}"
          if [[ "$BEFORE" == "0000000000000000000000000000000000000000" || -z "$BEFORE" ]] || \
             ! git rev-parse --verify "$BEFORE^{commit}" >/dev/null 2>&1; then
            BEFORE="$(git merge-base origin/main "$AFTER" 2>/dev/null || echo "$AFTER^")"
          fi
          git diff --name-only "$BEFORE"..."$AFTER" > build/changed-files.txt
          # `--numstat` so the reporter can apply policy.excludes to
          # the size budget (excludes-aware prSize).
          git diff --numstat "$BEFORE"..."$AFTER" > build/lines-per-file.txt
          python scripts/agent-redline-report.py \
            --policy agent-policy.yaml \
            --flow-mode push \
            --changed-files build/changed-files.txt \
            --lines-per-file build/lines-per-file.txt \
            --json-out build/verdict.json \
            --comment-out build/comment.md
          EXIT=$?
          echo "exit_code=$EXIT" >> "$GITHUB_OUTPUT"
          echo "--- verdict.json ---" && cat build/verdict.json
          echo "--- comment.md ---" && cat build/comment.md
          echo "reporter exit code: $EXIT"

      - name: Write verdict to job summary
        # Run-page summary is the human-readable surface; one click from
        # the failure-notification email, no artifact download.
        if: always()
        run: |
          {
            echo "## agent-redline verdict"
            echo
            cat build/comment.md
          } >> "$GITHUB_STEP_SUMMARY"

      - name: Upload verdict artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: agent-redline-verdict
          path: |
            build/verdict.json
            build/comment.md

      - name: Enforce reporter exit code
        # Push-mode: fail the workflow on EXIT != 0 (both RED warnings
        # and BOUNDARY_VIOLATION hard fails). The red badge on this
        # commit's agent-redline run is the audit record that the change
        # required human review; the next push that touches no red zone
        # produces a green run. GitHub's default workflow-failure email
        # notification fires for the user who triggered this run, which
        # is the "summon reviewer" channel for push-driven flow. Other
        # workflows in this repo are unaffected.
        run: |
          EXIT="${{ steps.report.outputs.exit_code }}"
          if [[ "$EXIT" != "0" ]]; then
            echo "Reporter exited $EXIT. Failing the agent-redline workflow."
            echo "See the run summary above for the full verdict."
            exit 1
          fi
          echo "Reporter exited 0 — clean."
```

(The reporter dispatches on `policy.boundaryAdapter`, which declares `outputFormat: json-violations` and `outputPath: build/import-linter-report.json` — the file the boundary job uploaded.)

## 6. Pre-push integration

`scripts/agent-redline-check.sh` (vendored from the skill at bootstrap) already runs the import-linter adapter before invoking the reporter when it sees `scripts/run-import-linter.py` in the consuming repo. No additional wiring needed.

## 7. Baseline for retrofit cases

Run `python scripts/run-import-linter.py --out /tmp/baseline.json` during Phase 1 inspection. If contracts already fail on `main`:

- Surface this in the bootstrap output. Don't quietly start enforcing.
- Two paths:
  1. **Use `ignore_imports` to baseline.** Add the existing violations as `ignore_imports` entries in each broken contract; the contract starts clean and only fails on new violations. Document the baselines as technical debt.
  2. **Set `modes.default: shadow` for boundary checks.** The reporter surfaces violations in the PR comment but doesn't fail CI. Flip to `binding` once the baseline is paid down.

Pick (1) when there are <10 violations; pick (2) when there are more.

## 8. OpenAPI / API diff (optional, v1)

For services that commit an OpenAPI spec:

```yaml
api:
  type: openapi-spec-file
  specPath: openapi/openapi.json
  diffMode: structural
  checkpoint: api-review
```

The reporter detects api changes by matching the diff against `specPath`.

For services that generate the spec from FastAPI / DRF / Flask-RESTX, generation-from-code is roadmap. v1 falls back to path-touch on routers/views/controllers (watch list) plus this committed-spec option.

## 9. Django-specific scaffolding

If the Django addendum applies (see `profile.md` "Shape: layered service → Django addendum"):

- Add the cross-app `independence` contract.
- Add the views-don't-reach-into-other-apps' `forbidden` contract.
- Add `DJANGO_SETTINGS_MODULE` to the CI environment so `import-linter` can resolve Django app modules:
  ```yaml
  - run: python scripts/run-import-linter.py --out build/import-linter-report.json
    env:
      DJANGO_SETTINGS_MODULE: <project>.settings
  ```
- Confirm the apps directory matches `INSTALLED_APPS` in `settings.py`. If they disagree, surface and ask the developer.

## 10. Generated files

Python projects with code generation (Strawberry GraphQL schemas, gRPC stubs, Pydantic-from-spec) produce files that should be in `excludes:`:

```yaml
excludes:
  - "**/*_pb2.py"
  - "**/generated/**"
  - "**/<pkg>/_generated/**"
```

If you find generated sources that aren't excluded, surface in the PR description and suggest a policy update.
