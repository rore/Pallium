# bootstrap-mode

Active when the developer asks you to set up agent-redline for a repo. Conversational, not silent.

## Output

**Committed directly:**
- `agent-policy.yaml`
- Reference section appended to the existing agent-instruction file (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `copilot-instructions.md`, or a fresh `AGENTS.md` if none exists)
- Boundary-rule backend artifacts — *only if no existing setup is found*; otherwise the policy's `boundaries:` mirror the existing rules and the existing test stays authoritative
- `scripts/agent-redline-check.sh` — standalone if no pre-push hook exists; otherwise instructions for the developer to chain
- `.github/pull_request_template.md` additions
- Per-checkpoint docs in `docs/agent/`

**Proposed, NOT committed:**
- `docs/agent-redline-ci-proposal.md` — workflow YAML, branch-protection changes, CODEOWNERS additions

## Phases

Each phase ends with a developer review or confirmation. Do not skip ahead.

1. Inspect and pick an extension
2. Extension-driven proposal
3. Adapt
4. Write
5. Propose CI
6. Self-summary

## Phase 1 — Inspect and pick an extension

Read what's in the repo:
- Build files (`build.gradle`, `pom.xml`, `package.json`, `pyproject.toml`, `setup.py`, `setup.cfg`, `go.mod`, `Cargo.toml`)
- Source layout. For Python: `src/<pkg>/` vs flat `<pkg>/` vs multi-package (multiple top-level `__init__.py` dirs, none matching the project name). For Django: `manage.py` at root.
- Existing agent-instruction file: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `copilot-instructions.md`, or any `*-instructions.md` at repo root
- Existing CI (`.github/workflows/`, `.gitlab-ci.yml`) — note the trigger (`pull_request:` vs `push:`)
- Recent flow signal: `gh pr list --state merged --limit 30 --json number` count vs `git log --since="3 months ago" --pretty=format:%h | wc -l`. Compare to gauge dominant flow (PR-driven vs push-driven)
- Existing CODEOWNERS
- Existing **boundary-rule backend setup**:
  - JVM/Spring: ArchUnit test classes (search `src/test/**` for files importing `com.tngtech.archunit`).
  - Python: `[tool.importlinter]` in `pyproject.toml`, `.importlinter`, or `[importlinter]` in `setup.cfg`.
  Treat existing rules as authoritative.
- Existing `pre-push` hook (`.git/hooks/pre-push`) or pre-push script (`scripts/pre-push*`)
- OpenAPI / GraphQL / proto files; SpringDoc plugin; FastAPI committed `openapi.json`
- DB migration directories (`db/migration/**`, `**/alembic/versions/**`, `**/migrations/**`)
- Security/auth code locations

Propose a language extension:
- Spring Boot + Gradle/Maven → `spring-archunit`
- Python (web service, library, or pipeline) → `python` — see "Python shape selection" below
- Other stacks → see [agent-redline EXTENSIONS docs](https://github.com/rore/agent-redline/blob/main/docs/EXTENSIONS.md); ask developer to pick a third-party one or proceed without one
- No extension available → offer zone-only governance (no boundary backend)

Don't modify anything yet. Produce a written summary; wait for developer confirmation. The summary must include:
- Whether an existing arch test or import-linter config was found, and if so its rules — Phase 4 composes with it, doesn't replace it
- Which agent-instruction file exists (if any) — Phase 4 adds a reference section there, not a fresh `AGENTS.md`
- Whether an existing pre-push hook exists — Phase 4 chains, doesn't replace

### Python shape selection

`python` covers three shapes — `profile.md` enumerates them in detail. Quick triage:

| Signal | Shape |
|---|---|
| `manage.py` at root + `django` in deps | layered service + Django addendum |
| Any web framework dep (fastapi/flask/starlette/aiohttp/etc.), or layer dirs (`domain/`, `adapters/`, `infrastructure/`, `core/`, `services/`, `usecases/`, `ports/`) | layered service |
| `pyproject.toml` `[project]`, no web dep, package with `__init__.py` re-exports | library / package |
| `airflow`/`prefect`/`dagster`/`luigi` deps, or `dags/` / `pipelines/` / `notebooks/` | zone-only fallback |
| None match | zone-only fallback |

Confirm before loading `profile.md` details. If two shapes could fire, present both. Layout (src-layout / flat / multi-package) is bootstrap-derived, not a separate shape.

### Flow mode (CI shape)

Pick one. Affects Phase 5's CI proposal — not the policy, not the skill discipline.

| Signal | Flow mode |
|---|---|
| Existing workflow has `on: pull_request:`, multiple recent merged PRs, multiple committers | PR-driven |
| Existing workflow has `on: push:`, ~zero merged PRs, dominant flow is `git push` to main | push-driven |
| Solo developer, no PRs (or PRs only for meta-changes), trunk-based | push-driven |
| Mixed (some PR work, some direct push) | dominant signal wins; ask the developer |

PR-driven proposes a workflow on `pull_request:` with a sticky comment surfacing the verdict; CI fails only on exit 2 (binding-mode hard fail). Push-driven proposes `on: push:` with the verdict in a CI artifact + workflow log; CI fails on exit 1 OR 2 (no sticky-comment surface, so warnings need CI red as their visibility channel). Both reference `extensions/<name>/scaffold.md` §5 (Python) or §6 (Spring) for the specific YAML.

Ask the developer for confirmation before drafting the CI proposal in Phase 5.

## Phase 2 — Extension-driven proposal

Load the chosen extension's `profile.md`. Adapt its defaults to the actual repo:
- Substitute placeholder package names with the actual ones from inspection. If the repo uses `core` instead of `domain`, translate the patterns.
- Skip zones that don't apply (no Terraform → omit the Terraform red entry).
- **Use the extension's PR-size thresholds verbatim.** The extension's `profile.md` has a "Default PR-size thresholds" section. Copy those numbers into the draft policy as-is. Don't invent values; the developer can adjust them in Phase 3.
- Don't fabricate.

Present a draft `agent-policy.yaml` with terse one-line comments. Show it for review before writing.

Sketch (`...` and `[...]` are placeholders for shape, not real values):

```yaml-sketch
version: 1
project: { name: <repo-name>, extension: <extension-name> }

zones:
  red:    [...]
  blue:   [...]
  watch: [...]

boundaries: [...]
api: { type: ..., ... }
persistence: { migrationPaths: [...] }
security: { paths: [...] }
runtimeConfig: { paths: [...] }

prRules:
  maxChangedFiles: { warn: 50, fail: 100 }
  maxLinesChanged: { warn: 1000, fail: 2000 }

checkpoints:
  architecture-review: { satisfiedBy: [codeownerApproval, label: architecture-reviewed] }
  api-review: { ... }

modes:
  default: shadow
  perCheck: { boundary_violation: binding }
```

Comments terse.

## Phase 3 — Adapt

### 3a. Zone-utility check (mandatory)

Red means **different review behavior**, not "important code" (SPEC §4). A red zone that fires on a typical feature PR is alert fatigue — the team will learn to ignore it, and you've made the project worse, not better.

For each red entry in the draft policy, walk through:

1. **Does this path change in ordinary feature PRs?** Pick three recent feature PRs and ask the developer.
2. **If yes — are most of those changes truly architectural decisions?** Adding a field to an entity isn't. Renaming a domain class is. New endpoint methods are. Refactoring private methods isn't.
3. **If most are routine — downgrade.** Move the path to `watch` (still surfaced, no checkpoint) or to `blue` (autonomous). Do not leave it as red because "the code is important." Important + routine = `watch`.
4. **If the path mixes routine and structural** — try to split it. `domain/repository/*.java` (interfaces, structural) vs `domain/repository/impl/**` (often routine). The Spring profile defaults already do this where viable; do it again for repo-specific paths.
5. **Prefer semantic over path-based triggers** when both exist. The `api:` openapi-diff is precise; controller-touch isn't.

This is a **starting hypothesis**. The first 2-4 weeks of shadow mode is where the team confirms or corrects it (Phase 5 / CI proposal).

### 3b. History-based calibration (when applicable)

The tuner takes a list of changesets and reports which red/watch rules fire most often. The unit of changeset depends on the flow mode:

- **PR-driven flow:** count merged PRs via `gh pr list --state merged --limit 1 --json number`. If 30+, run the tuner with `--repo <gh-slug> --limit 30`.
- **Push-driven flow:** count commits to the long-lived branch via `git rev-list --count main`. If 30+, run with `--push-history --branch main --limit 30`. Each push range (or commit, for solo repos pushing one commit at a time) becomes one changeset.

If fewer than 30 changesets exist either way, skip 3b; note in the policy comment that calibration will complete in Window 1 of shadow mode. Otherwise ask: *"I can run the tuner against the last 30 changesets to see which red rules fire too often. Run it?"*

On approval, run the tuner from the agent-redline skill (not the consuming repo): `python <skill-root>/scripts/agent-redline-tune.py --policy <draft-path> [--repo <slug> --limit 30 | --push-history --branch main --limit 30] --suggest`. The tuner reads only — it queries GitHub via `gh` (PR mode) or `git log` (push mode) and writes nothing into the consuming repo.

Present each suggestion: path, firing rate, current zone, proposed action. Ask the developer to approve, override, or split. For approved demotions, move the path from `red` to `watch` in the draft. For overrides, add a one-line comment in the policy: `# kept red despite NN% rate: <reason>`.

Never auto-apply suggestions. Never run the tuner without confirmation.

### 3c. Repo-specific questions

Ask:
- Third-party adapter contracts that should be red?
- Customer-specific code that must not leak into shared core?
- Multi-tenant persistence with rollout-plan implications?
- Generated source directories to exclude from classification?
- Who owns architecture / API / persistence / security / ops review?
- Normal PR size for this team — adjust thresholds?
- Existing arch tests / import-linter contracts / CODEOWNERS / CI checks to compose with?

Update the draft. Show it. Get explicit sign-off before writing.

If the developer disagrees with extension defaults, the developer wins. Note overrides explicitly.

## Phase 4 — Write

Once signed off, write the committed artifacts.

**`agent-policy.yaml`** — must classify the boundary-backend definition files as red (e.g., `src/test/java/**/architecture/**` for ArchUnit, `pyproject.toml` and `.importlinter` for import-linter, or wherever the existing config lives in this repo). Verify it parses against `assets/schema/agent-policy.schema.json`.

**Agent-instruction file** — if `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `copilot-instructions.md`, or a similar file already exists at the repo root, append the agent-redline reference section from `assets/templates/AGENTS.md.template` (drop the `# AGENTS.md` heading; keep the body) under a clearly-marked heading. Do NOT create a new `AGENTS.md` alongside an existing instruction file. If none exists, copy `assets/templates/AGENTS.md.template` verbatim as `AGENTS.md`.

**Boundary-rule backend artifacts** — read the extension's `scaffold.md`. Two cases:

- **Existing setup found in Phase 1** (ArchUnit test, `[tool.importlinter]` block, etc.): do NOT generate a new one. Translate its rules into `boundaries:` entries in the policy (one per rule). The policy's `boundaries:` is metadata the reporter surfaces; the existing setup does the actual checking.
- **No existing setup:** generate per `scaffold.md`. Substitute the actual base package. Don't write `..domain..` if the repo uses `..core..`.

**Vendor the reporter** — copy `scripts/agent-redline-report.py` (which the packaged skill ships as `scripts/agent-redline-report.py`) into the consuming repo at `scripts/agent-redline-report.py`, mark executable. The pre-push script and CI workflow both invoke it.

**`scripts/agent-redline-check.sh`** — copy `assets/templates/pre-push-check.sh` verbatim, mark executable. Do NOT regenerate; a hand-rolled version will drift from CI.

If a pre-push hook already exists, do NOT replace it. Chain: have it call `./scripts/agent-redline-check.sh`, or vice versa.

**PR template** — copy `assets/templates/pr-template.md` verbatim into `.github/pull_request_template.md`. If one already exists, append the agent-redline sections under a marked heading.

**Per-checkpoint docs** — copy from `references/per-checkpoint/` into `docs/agent/`. Always: `blue-zone-work.md`, `red-zone-change.md`, `gray-zone-change.md`, `boundary-violation.md`, `pr-discipline.md`. Add `api-change-checkpoint.md`, `persistence-change-checkpoint.md`, `security-change-checkpoint.md` only when the policy declares that checkpoint.

**Templates are copied, not regenerated.** Hand-rolling drifts from the reporter and schema. Edit the copy *after* it lands if consumer-specific values are needed.

## Phase 5 — Propose CI

Write `docs/agent-redline-ci-proposal.md`. Do NOT write `.github/workflows/agent-redline.yml`.

Tell the developer:

> CI integration affects every developer and may need platform-admin approval. I've written everything I'm allowed to write directly. Open `docs/agent-redline-ci-proposal.md`, review with whoever owns CI, apply when ready.

The proposal contains:
1. Proposed workflow file (ready to copy) — pick the PR-driven or push-driven shape per Phase 1's flow-mode triage
2. Required-status-check additions for branch protection (PR-driven only — solo / push-driven repos skip this)
3. CODEOWNERS additions, mapped best-effort to teams from Phase 3 (PR-driven only — push-driven repos skip)
4. **Recommended initial mode: shadow.** 4 weeks or 30 PRs of shadow before flipping anything to binding. Push-driven repos use commits (not PRs) as the calibration unit — see Phase 3b for the `--push-history` tuner mode.
5. **Boundary-backend baseline** if running the backend on `main` surfaces existing violations: capture them, fail CI for *new* violations only.
6. Decisions explicitly flagged for human judgment.

The workflow YAML invokes the standalone reporter directly. The reusable Action is roadmap; don't reference it as if it exists.

## Phase 6 — Self-summary

- What was committed (file list)
- What was proposed but not committed (the CI proposal)
- What still needs human action (apply CI proposal, set up branch protection, replace placeholder team names, run shadow mode)
- How to verify the local check works
- Where the docs live

Be honest about anything you couldn't classify cleanly.

## Hard rules

- Never auto-commit CI workflow files, branch-protection changes, or CODEOWNERS additions.
- Never overwrite an existing `agent-policy.yaml` without confirmation.
- Never overwrite an existing arch test or import-linter config (or other boundary-backend definition). Compose via `boundaries:` instead.
- Never overwrite an existing agent-instruction file. Append a reference section.
- Never overwrite an existing pre-push hook. Tell the developer how to chain.
- The generated policy must classify the boundary-backend definition files as red (`architecture-review` checkpoint).
- The generated policy must classify itself (`agent-policy.yaml`) as red with `architecture-review`. Without this, an agent can drop the red rule blocking its change and ship unchallenged.
- Write artifacts only after the developer signs off on the policy in Phase 3.

## When the repo doesn't fit

If inspection finds no recognizable structure to protect — no domain/adapter split, no port interfaces, no API surface, no migrations:

1. **Decline.** Tell the developer agent-redline only protects boundaries the team is willing to name. Suggest explicit modeling work first.
2. **Partial bootstrap.** Cover only the parts that *do* have structure (security paths, runtime config, migrations if any). Skip boundary rules until there's structure to enforce.

Don't fabricate architecture the codebase doesn't have.
