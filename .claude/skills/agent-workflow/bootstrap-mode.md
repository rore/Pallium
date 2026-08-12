# bootstrap-mode

Active when the developer asks you to set up agent-workflow on a repository. Conversational. Walks the repo from no-config to a fully-installed harness.

## Pre-flight

Runs when `agent-workflow.yaml` is **not** present at the repo root. If you find one, switch to [`operating-mode.md`](operating-mode.md) — bootstrap doesn't re-install over a configured repo (see "Re-bootstrap" near the end).

agent-workflow ships with [agent-redline](agent-redline/SKILL.md) bundled. Bootstrap installs both together. Do not ask whether to include redline. If redline is already installed (e.g. via its own bootstrap), bootstrap detects and adopts it without re-installing.

## Output

| Category | What lands | When |
|---|---|---|
| **Committed directly** | the skill itself under `.claude/skills/agent-workflow/`, `agent-workflow.yaml`, `agent-redline-policy.yaml`, vendored `scripts/agent-workflow-check.py`, vendored `scripts/agent-redline-report.py`, AGENTS.md reference section, `.agent-redline/suppressions.yaml`, per-checkpoint docs under `docs/agent-redline/skills/`, `.agent-workflow/tasks/README.md` skeleton | Phase 4, after Phase 3 sign-off |
| **Committed only with explicit confirmation** | `.github/workflows/agent-workflow.yml` | Phase 5, if developer confirms |
| **Proposed but never committed by bootstrap** | `docs/agent-workflow-ci-proposal.md` (branch-protection + required-status-checks + CODEOWNERS additions). Workflow file goes here too when developer declines Phase 5. | Phase 5 |
| **Final summary** | `docs/agent-workflow-bootstrap-summary.md` | Phase 6 |

The split between "committed directly" and "committed only with confirmation" is not negotiable. CI workflows gate every contributor's PR; the developer must see and confirm. Branch protection and CODEOWNERS need platform-admin access bootstrap can't have — they go to the proposal doc regardless.

**The skill itself is a committed artifact.** Bootstrapping commits the skill *in* the repo at `.claude/skills/agent-workflow/` — not a per-developer user/workspace install, which activates for one machine and silently does nothing for every other checkout. Committed alongside the `scripts/agent-workflow-check.py` and `agent-workflow.yaml` it reads, all three stay version-locked and `/agent-workflow` auto-activates for anyone — teammate, fresh agent, CI. (This repo gitignores its own `.claude/skills/` only because it regenerates from the tracked `dist/agent-workflow/` tree; a consumer has no such source.)

## Phases

1. Inspect
2. Propose
3. Adapt
4. Write
5. Confirm CI
6. Self-summary

Each phase ends with developer review or a defined notification. Do not skip ahead. If a phase fails because an input is missing or ambiguous, pause and ask — don't fabricate.

## Before Phase 1 — write the Work Record for THIS task

Bootstrap is itself an engineering task. Operating-mode discipline applies: **write a Work Record before starting.**

Path: `.agent-workflow/tasks/bootstrap-<repo-name>.md` in the **target** repo. Use the **expanded shape** — bootstrap touches CI, policy, and AGENTS surfaces (default profile §3 classifies as Elevated; never compact).

Minimum fields before Phase 1:

- **Outcome:** install agent-workflow on the target repo
- **Target:** the repo's name + branch
- **Scope:** what bootstrap will write (the skill under `.claude/skills/agent-workflow/` + config + policy + binaries + AGENTS.md + per-checkpoint docs + CI workflow if confirmed)
- **Constraints:** hard rules from this skill (never overwrite, never modify CI without confirmation, etc.)
- **Completion criteria:** Phase 6 self-summary written + backend probe pass
- **Risk:** Elevated (default; raise to High if the target repo is canonical or has live consumers)
- **Complexity:** Simple for stub / fresh repos; Moderate for repos with existing tools to compose with
- **Reason:** "bootstrap installs CI gates and AGENTS.md — default profile §3 Elevated"
- **Plan:** "walk bootstrap's six phases per the skill"
- **Verification plan:** "Phase 6 self-summary's backend probe + CI green on the resulting PR"
- **State:** `Ready to implement`

Update State to `Ready for review` when Phase 6 finishes. Populate Implementation prose one line per phase as you go. Evidence prose names the probe outcome + (post-PR) the CI verdict.

If the delegating agent already wrote a Work Record for the bootstrap task, **read it** and update its sections as you go. Don't write a second one.

## Phase 1 — Inspect

Compose with redline's Phase 1 (see [`agent-redline/bootstrap-mode.md`](agent-redline/bootstrap-mode.md) §"Phase 1"). Don't replicate redline's inspection; invoke it.

Read on the agent-workflow side:

- **Existing agent-workflow install:** `agent-workflow.yaml` at repo root (if found, should have switched to operating-mode — sanity-check).
- **Existing redline install:** `agent-redline-policy.yaml`; contents of `agent-redline/`. If present, you compose in Phase 2.
- **Existing agent-instruction file:** `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `copilot-instructions.md`, or any `*-instructions.md` at the repo root. First one found wins; bootstrap appends. If none, bootstrap writes a fresh `AGENTS.md`.
- **Authoritative-source map:** what existing files this repo treats as canonical for *what the system should do* (requirements, Jira), *how it's organised* (architecture, ADRs), and *what was decided* (`DECISIONS.md`). Bootstrap doesn't invent these; it lists what it found.
- **Existing CI:** `.github/workflows/`. Note whether `agent-workflow.yml` exists, name collisions on `redline-verdict`, and dominant trigger style (`pull_request:` vs `push:`).
- **Existing CODEOWNERS:** `.github/CODEOWNERS` or `CODEOWNERS` at root. Bootstrap doesn't modify it.
- **Flow signal:** `gh pr list --state merged --limit 30 --json number` vs `git log --since="3 months ago" --pretty=format:%h | wc -l`. Used to pick PR-driven vs push-driven; agent-workflow CI template assumes PR-driven.
- **Workflow tuner (slice G2):** if repo is org-scoped (`<org>/<name>`), has ≥10 merged PRs, and `gh` is authenticated, run `python <install-root>/scripts/agent-workflow-tune.py --repo <slug> --limit 30`. Capture **Calibration suggestions** for Phase 2 and **Proposed `.github/CODEOWNERS`** for Phase 3. If `## Inspection skipped: <reason>` is emitted, note the reason; Phase 3 falls back to `@TODO-codeowners-team` placeholder.

Then invoke redline's Phase 1 (extension pick, build files, source layout, boundary-rule backend, pre-push hook).

**Greenfield / no-build-file repos.** Redline's extension-pick uses positive signals from build files. A repo with source under `src/main/java/...` but no `build.gradle*` or `pom.xml` falls through to `zone-only` — correct. Surface as "no build file detected" and defer the build-tool choice to the developer before Phase 2 drafts boundary-rule shape.

**Phase 1 output: a finding block.**

```
## Bootstrap inspection — Phase 1 finding

**Existing agent-workflow install:** <yes / no>
**Existing redline install:** <yes (path, version) / no>
**Existing agent-instruction file:** <path or "none">
**Authoritative sources found:** <requirements / architecture / decisions — paths or "none">
**Existing CI:** <paths to workflows / "none">
**Existing CODEOWNERS:** <yes / no>
**YAML-formatting gate:** <yes (Spotless/jackson-YAML — `agent-workflow.yaml` + policy must be canonical) / no>
**Detected flow mode:** <PR-driven / push-driven / mixed>
**Detected language extension** (from redline's Phase 1): <jvm-archunit / python / other / zone-only>
**Detected language shape** (if applicable): <layered service / library / zone-only fallback>
**Boundary-rule backend setup found:** <yes (path) / no>
**Pre-push hook found:** <yes (path) / no>

**Decisions deferred to developer:**
- <each open question>

**Notes:**
- <anything unusual>
```

Do not move to Phase 2 until the developer confirms the finding (or corrects it).

## Phase 2 — Propose

Two drafts side by side, inert. Nothing on disk yet.

### Draft 1: `agent-workflow.yaml`

```yaml-sketch
version: 1
project: { name: <repo-name> }
workRecord:
  backend: local                              # only supported backend
  local: { taskPath: ".agent-workflow/tasks/{slug}.md" }
redline: required                             # bundled
redlineVerdictPath: redline-verdict.json      # CI artifact path
hooks:
  guardedPaths:                               # code root(s) the plan-mode gate guards
    - "src/"
```

Backend is always `local`. The taskPath template is the canonical default; don't customize without a developer reason.

**`hooks.guardedPaths`** — the plan-mode gate hook (4.3h) requires a plan to include the Work Record step when it touches these path prefixes. Detect this repo's code root(s) from inspection (the layout that holds the code redline treats as sensitive — e.g. `src/` for a standard Maven/Gradle repo, or the actual top-level dirs like `core/`, `lib/`, `app/`), propose them here, and confirm with the developer in Phase 3. Prefixes match on a path boundary, case-insensitively. If omitted the gate defaults to `["src/"]`.

### Draft 2: `agent-redline-policy.yaml`

Invoke redline's Phase 2 ([`agent-redline/bootstrap-mode.md`](agent-redline/bootstrap-mode.md) §"Phase 2"). Adapt the chosen extension's `profile.md` to this repo. Show the draft inline.

Present both drafts. State the ask:

> Both drafts above are inert — nothing has been written yet. Review and we'll adapt in Phase 3.

## Phase 3 — Adapt

Walk redline Phase 3 checks (zone utility, history-based calibration when ≥30 changesets, repo-specific questions). See [`agent-redline/bootstrap-mode.md`](agent-redline/bootstrap-mode.md) §"Phase 3".

Ask the developer **only** what the inspection didn't already answer:

- Repository-local paths the policy should treat specially that didn't surface in inspection?
- PR-driven vs push-driven? (Confirm Phase 1's detection.)
- Per-checkpoint reference docs under `docs/agent-workflow/` (default) or somewhere else?

Update both drafts. Show revised drafts. Loop until explicit sign-off.

## Phase 4 — Write

Write the committed artifacts. Branch each step on existing files; never overwrite without confirmation.

| Step | Path | Branch on existing |
|---|---|---|
| 4.0 | `.claude/skills/agent-workflow/` | Commit the skill itself — the whole tree (`SKILL.md`, `operating-mode.md`, `bootstrap-mode.md`, `agent-redline/`, `templates/`, `scripts/`, `assets/`, `hooks/`) copied **verbatim from a single install source** — `dist/agent-workflow/` in a pinned clone of the agent-workflow repo, or `<install-root>`. Copy the whole directory (`cp -r`); do **not** hand-fetch files one at a time from the API — an incomplete/garbled sync is the failure mode the Phase 6 manifest check exists to catch. A real commit, not a local regen; do **not** gitignore `.claude/skills/`. If it already exists, this is a **re-bootstrap** (updating to a newer version): that is itself a tracked task — you should already hold a Work Record for it (operating-mode) before touching files — so refresh the tree here and let steps 4.1/4.4 reconcile config + the agents-section rather than stopping. |
| 4.1 | `agent-workflow.yaml` | If exists, you should have switched to operating-mode — sanity-check and stop. Otherwise write the Phase 3 draft. **If Phase 1 found a YAML-formatting gate** (Spotless/jackson-YAML), emit it in the formatter's canonical style so it survives `./gradlew build` — same rule the redline policy uses (`agent-redline/bootstrap-mode.md` §Phase 4): **no `#` comments** (put rationale in the WR/PR, not the YAML) and **quote every string scalar**; keep block sequences (the template is already block-form — do not collapse to `["src/"]`). Do not assume a `---` document-start; match whatever the formatter emits. Run `./gradlew spotlessApply` (or the repo's format task) after writing and commit the result so CI starts clean. |
| 4.2 | `agent-redline-policy.yaml` | If exists, do **not** overwrite. Mirror existing in the finding; adopt. Otherwise write the Phase 3 draft. |
| 4.3 | `scripts/agent-workflow-check.py` | Always write. Build from dev repo via `bash scripts/build-vendored-checker.sh <output>`. If you can't run that, copy from `<install-root>/scripts/agent-workflow-check.py`. If neither, stop and tell the developer. |
| 4.3 | `scripts/format-verdict-comment.py` | Copy `<install-root>/scripts/format-verdict-comment.py`. The CI workflow step `Format verdict for PR comment` invokes it. |
| 4.3 | `scripts/agent-redline-report.py` | Copy `<install-root>/agent-redline/scripts/agent-redline-report.py`. |
| 4.3h | `.claude/hooks/` + `.claude/settings.json` | Copy the hook files from `<install-root>/hooks/` into `.claude/hooks/` (committed), then run `python .claude/hooks/install-settings.py` to register the seed/gate/reinforce hooks (idempotent create-or-merge; never removes existing hooks; refuses on invalid JSON). The installer also reads `hooks.guardedPaths` from `agent-workflow.yaml` (written at 4.1, so run this after) and writes the gate's `guarded-paths.json` sidecar; if the key or pyyaml is absent the gate defaults to `src/`. Keeps the workflow engaged in plan mode — a nudge, not the CI floor. |
| 4.4 | AGENTS.md reference section | Marker-wrapped. No existing instruction file → fresh `AGENTS.md` from `templates/agents-section.md.template`. Existing instruction file, no markers → append the marker-wrapped section. **Existing markers (re-bootstrap) → reconcile, don't skip:** run `python <install-root>/hooks/merge-agents-section.py --file <instruction-file> --template <install-root>/templates/agents-section.md.template` — it refreshes only the bytes between the markers to the current template (idempotent; leaves surrounding prose byte-identical). Skipping when markers exist silently freezes the section at its first-installed version. |
| 4.5 | `.agent-redline/suppressions.yaml` | Invoke redline's Phase 4 write step. |
| 4.6 | `docs/agent-redline/skills/` | Invoke redline's Phase 4 write step. |
| 4.7 | `docs/agent-workflow/` | Copy `templates/checkpoints/*.md` from the installed skill. |
| 4.8 | `.agent-workflow/tasks/README.md` | Skeleton explaining the `{slug}.md` convention; references operating-mode.md. |

### 4.4 marker shape

```
<!-- agent-workflow:agents-section:start -->
... content from templates/agents-section.md.template ...
<!-- agent-workflow:agents-section:end -->
```

### Hard rules

- Never overwrite an existing `agent-workflow.yaml` without explicit developer confirmation.
- Never overwrite an existing `agent-redline-policy.yaml` (composition only — adopt the existing policy).
- Never modify existing content of `AGENTS.md` / `CLAUDE.md` / etc. outside the agent-workflow marker block — append only. The one exception is the marker-wrapped agents-section itself, which `merge-agents-section.py` reconciles in place on re-bootstrap (it touches only the bytes between the markers).
- Never modify boundary-rule backend definitions (existing ArchUnit tests, import-linter configs). The redline policy's `boundaries:` mirrors them; the existing test stays authoritative.
- Never write `.github/workflows/*.yml` in Phase 4. That's Phase 5's job, and only with confirmation.

## Phase 5 — Confirm CI

Bootstrap diverges from redline's "always proposal-only" stance.

### 5.1 Always proposal-only

Write `docs/agent-workflow-ci-proposal.md`. Always. Content:

- **The combined two-job workflow file** (ready to copy) — derived from `templates/.github/workflows/agent-workflow.yml.template`. Substitute repo-specific values if any (rare; the template is parameterized).
- **Required-status-check additions** for branch protection: name the **bare job names** as required checks — `agent-workflow` and `redline`. GitHub Actions reports each job by its job name (not `workflow / job` — display-only). A workflow-prefixed name causes GitHub to wait forever; learned from PR #32 dogfooding.
- **Require conversation resolution** before merge: turn on `required_conversation_resolution` in the branch-protection rule. GitHub then refuses merge while any review thread is unresolved (line comments, review summaries, bot threads). Pairs with operating-mode §7 — the platform enforces what the skill teaches.
- **CODEOWNERS additions** — when the Phase 1 tuner ran, paste its **Proposed `.github/CODEOWNERS`** block verbatim. When the tuner skipped (no PR history, not org-scoped), fall back to `@TODO-codeowners-team` placeholder and note in the Phase 6 summary why. Self-protecting paths (`agent-redline/**`, `agent-workflow.yaml`) get an explicit override pointing at the same team as default `*`; when default is `@TODO-*`, propagate the placeholder.
- **Recommended initial mode for redline:** `shadow` for 4 weeks / 30 PRs before flipping to binding (per redline's Phase 5).
- **Decisions explicitly flagged for human judgment** — every line the developer needs to inspect.

### 5.2 The confirmation prompt

Show the proposed workflow file to the developer and ask, in exactly this shape:

> CI integration is necessary to complete the install. Without the workflow file, every PR runs without the redline + agent-workflow gates — the harness operates on trust until a human applies the proposal manually.
>
> I can install the workflow file directly at `.github/workflows/agent-workflow.yml`, OR write it only to the proposal doc for you to apply when ready. Branch protection rules and CODEOWNERS changes will go to the proposal doc regardless — they need platform-admin access I don't have.
>
> Install the workflow file now? (yes / proposal-only)

If **yes / install / confirmed**:
- Write `.github/workflows/agent-workflow.yml` directly from the template.
- Update `docs/agent-workflow-ci-proposal.md` to record "Workflow file installed on <date>; branch protection and CODEOWNERS additions still need human action."
- Phase 6 CI section says "Workflow installed; branch protection still needs human action."

If **proposal-only / no / defer**:
- Do NOT write `.github/workflows/agent-workflow.yml`.
- Leave the workflow file content prominently at the top of `docs/agent-workflow-ci-proposal.md`.
- Phase 6 CI section says "Workflow not installed — apply the proposal doc when ready. Branch protection and CODEOWNERS additions also need human action."

### 5.3 Hard rules

- Branch protection rules and CODEOWNERS additions go to the proposal doc **regardless** of which way the developer answers. Bootstrap does not have the access to apply them.
- If `.github/workflows/agent-workflow.yml` already exists when the developer confirms install, ask before overwriting.
- Copy the workflow template first. Repo-specific edits may change runner labels, Python install/setup steps, or action versions; they must preserve `needs: [redline]`, verdict artifact upload/download, `--changed-files`, `--redline-verdict`, captured checker/reporter exit codes, and distinct sticky headers.

## Phase 6 — Self-summary

Write `docs/agent-workflow-bootstrap-summary.md` from [`templates/bootstrap-summary.md.template`](templates/bootstrap-summary.md.template). Three named sections: Installed (committed directly), Proposed (uncommitted), Needs human action. Each item names a specific governance control and its outcome. The template carries the table structure verbatim — fill in the per-row `<placeholder>` values.

### Run the probe

Before writing the summary's "Backend reachability probe" section, actually run the probe:

1. Write a temporary Work Record at `.agent-workflow/tasks/_probe.md` — minimal compact-shape with `**State:** Ready for review`.
2. Run `python scripts/agent-workflow-check.py --repo-root . --slug _probe`. The checker should exit clean (or advisory — `redline: required` + no verdict on a local probe gives advisory; fine for the probe).
3. Record the outcome in the self-summary.
4. Delete the probe file.

If the probe fails, name the reason in the self-summary's "Could not verify" section and do not delete the probe file — leave it for the developer to inspect.

### Verify the install is real (not just written)

Two things a green probe does NOT catch — check both; both have silently passed every gate on real installs:

- **Skill resolvable.** Confirm `.claude/skills/agent-workflow/SKILL.md` exists in the target repo. If absent, the CLAUDE.md pointer at `/agent-workflow` is a dead reference (see Phase 4 step 4.0) — hard-fail the bootstrap, tell the developer, don't write the summary as success.
- **Policy schema-valid.** Confirm `agent-redline-policy.yaml` validates against `.agent-redline/agent-policy.schema.json` (redline Phase 4 ran this; re-assert). A schema-invalid policy passes CI green while its semantics are dead.
- **Skill install complete.** Confirm every file in `.claude/skills/agent-workflow/manifest.txt` exists with the recorded byte size (forward check — catches a partial/garbled copy, the failure mode of hand-fetching files one by one). One-liner: `python - <<'PY'` reading the manifest and `os.path.getsize`, or eyeball on a small install. Missing/size-mismatch → the copy is incomplete; recopy from the source (below), don't proceed. (Do not fail on *extra* files — a run of the checker leaves `__pycache__`.)

### Show the self-summary in conversation

After writing the file, paste the rendered Markdown back into the conversation as the closing message. The developer should see what's installed, what still needs action, and where to find each item — without re-opening the file.

### Skill feedback check

Before showing the self-summary, walk this table. One row per trigger.

| Trigger | Did it happen during bootstrap? (Y/N) |
|---|---|
| 1. A bootstrap instruction was unclear and I had to guess what was intended. | |
| 2. Two bootstrap sections contradicted each other and I had to choose. | |
| 3. A cross-reference in the skill was broken (file missing, anchor missing). | |
| 4. A scaffold or template I wrote did not parse or did not match the schema (`agent-workflow.yaml`, `agent-redline-policy.yaml`, workflow YAML). | |
| 5. The backend probe failed and the failure pointed at a skill gap (not a repo-specific issue). | |
| 6. The Phase 5 confirmation prompt was ambiguous about what "yes" or "proposal-only" meant. | |

If any answer is yes, load [`templates/skill-feedback.md`](templates/skill-feedback.md) and follow it. If all are no, the check is done — proceed to show the self-summary.

## Re-bootstrap

If bootstrap is invoked on a repo that already has `agent-workflow.yaml`, stop. Tell the developer:

> agent-workflow is already installed here (`agent-workflow.yaml` at the repo root). I can't re-bootstrap over a configured repo from this skill. To re-run bootstrap, delete `agent-workflow.yaml` and the per-PR Work Records under `.agent-workflow/tasks/` first. To update the harness (re-vendor the checker, re-pull templates), use operating-mode and tell the agent what specifically to refresh.

Re-bootstrap should be deliberate, not accidental. Hard rule: one-shot install per repo.

## Hard rules (consolidated)

- Never overwrite an existing `agent-workflow.yaml` without explicit confirmation.
- Never overwrite an existing `agent-redline-policy.yaml` — adopt and compose.
- Never modify existing content of any agent-instruction file. Append a marker-wrapped section only.
- Never modify boundary-rule backend definitions. The redline policy's `boundaries:` mirrors them.
- Never write `.github/workflows/*.yml` outside Phase 5.
- Never modify branch protection or CODEOWNERS. Always proposal-only.
- Never proceed past Phase 3 without explicit developer sign-off on the policy drafts.
- Never claim "verified" for something bootstrap couldn't actually verify. The self-summary names every unverified item.

## When the repo doesn't fit

If Phase 1 finds no recognizable structure to protect — no source code, no architecture to classify, no PRs as the dominant flow — escalate. Bootstrap protects boundaries the team is willing to name. A repo with nothing to protect doesn't benefit; suggest the developer reconsider.

If the developer wants to proceed anyway, bootstrap with `redline:` covering only what does exist (security paths if any, runtime config, migrations). Don't fabricate architecture the codebase doesn't have.
