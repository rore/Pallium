# bootstrap-mode

Active when the developer asks you to set up agent-workflow on a repository. Conversational. Walks the repo from no-config to a fully-installed harness.

## Pre-flight

Runs when `agent-workflow.yaml` is **not** present at the repo root. If you find one, switch to [`operating-mode.md`](operating-mode.md) — bootstrap doesn't re-install over a configured repo (see "Re-bootstrap" near the end).

agent-workflow ships with [agent-redline](agent-redline/SKILL.md) bundled. Bootstrap installs both together. Do not ask whether to include redline. If redline is already installed (e.g. via its own bootstrap), bootstrap detects and adopts it without re-installing.

## Output

| Category | What lands | When |
|---|---|---|
| **Committed directly** | identical skill package under `.claude/skills/agent-workflow/` and `.agents/skills/agent-workflow/`, configs, vendored checker/reporter, `scripts/agent-workflow-runtime.py/.sh/.ps1`, merged Claude/Codex settings, owned root `AGENTS.md` marker, docs, Work Record skeleton, and stable OpenCode 1.x plugin | Phase 4, after Phase 3 sign-off |
| **Committed only with explicit confirmation** | `.github/workflows/agent-workflow.yml` | Phase 5, if developer confirms |
| **Proposed but never committed by bootstrap** | `docs/agent-workflow-ci-proposal.md` (branch-protection + required-status-checks + CODEOWNERS additions). Workflow file goes here too when developer declines Phase 5. | Phase 5 |
| **Final summary** | `docs/agent-workflow-bootstrap-summary.md` | Phase 6 |

The split between "committed directly" and "committed only with confirmation" is not negotiable. CI workflows gate every contributor's PR; the developer must see and confirm. Branch protection and CODEOWNERS need platform-admin access bootstrap can't have — they go to the proposal doc regardless.

**The skill package is a committed artifact.** Bootstrap copies the identical package into both `.claude/skills/agent-workflow/` and `.agents/skills/agent-workflow/` so Claude Code and Codex can discover it. Runtime adapters may degrade; CI remains authoritative. OpenCode support is stable 1.x only; OpenCode 2 beta is excluded.

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
- **Existing agent-instruction files:** inspect `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `copilot-instructions.md`, and any `*-instructions.md`; always create or reconcile only the owned marker in root `AGENTS.md` and preserve every other instruction file.
- **Authoritative-source map:** what existing files this repo treats as canonical for *what the system should do* (requirements, Jira), *how it's organised* (architecture, ADRs), and *what was decided* (`DECISIONS.md`). Bootstrap doesn't invent these; it lists what it found.
- **Existing CI:** `.github/workflows/`. Note whether `agent-workflow.yml` exists, name collisions on `redline-verdict`, and dominant trigger style (`pull_request:` vs `push:`).
- **Existing CODEOWNERS:** `.github/CODEOWNERS` or `CODEOWNERS` at root. Bootstrap doesn't modify it.
- **Flow signal:** `gh pr list --state merged --limit 30 --json number` vs `git log --since="3 months ago" --pretty=format:%h | wc -l`. Used to pick PR-driven vs push-driven; agent-workflow CI template assumes PR-driven.
- **Applicability candidates:** load [`applicability.md`](templates/checkpoints/applicability.md); discover actual documentation/roadmap/root-README paths and live default-branch protection. Do not assume path names.
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
**Applicability candidates + protection:** <exact paths / none>; <protected / unprotected / unavailable>

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

If candidates exist, add `applicability.documentationOnly` to the inert draft with exact paths. Set direct-default true only when live checks prove unprotected; otherwise false.

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

Update both drafts using the approval command in [`applicability.md`](templates/checkpoints/applicability.md); use only its emitted fragment. Direct-default needs separate approval. Show revised drafts until explicit sign-off.

## Phase 4 — Write

Write the committed artifacts. Branch each step on existing files; never overwrite without confirmation.

| Step | Path | Branch on existing |
|---|---|---|
| 4.0 | `.claude/skills/agent-workflow/` + `.agents/skills/agent-workflow/` | Copy the whole package verbatim from one install source (`dist/agent-workflow/` or `<install-root>`) to both paths; verify both manifests match. Existing installs are updated through operating mode, preserving config, hooks, and historical Work Records; never delete them to re-bootstrap. |
| 4.1 | `agent-workflow.yaml` | If exists, you should have switched to operating-mode — sanity-check and stop. Otherwise write the Phase 3 draft. **If Phase 1 found a YAML-formatting gate** (Spotless/jackson-YAML), emit it in the formatter's canonical style so it survives `./gradlew build` — same rule the redline policy uses (`agent-redline/bootstrap-mode.md` §Phase 4): **no `#` comments** (put rationale in the WR/PR, not the YAML) and **quote every string scalar**; keep block sequences (the template is already block-form — do not collapse to `["src/"]`). Do not assume a `---` document-start; match whatever the formatter emits. Run `./gradlew spotlessApply` (or the repo's format task) after writing and commit the result so CI starts clean. |
| 4.2 | `agent-redline-policy.yaml` | If exists, do **not** overwrite. Mirror existing in the finding; adopt. Otherwise write the Phase 3 draft. |
| 4.3 | `scripts/agent-workflow-check.py` | Always write. Build from dev repo via `bash scripts/build-vendored-checker.sh <output>`. If you can't run that, copy from `<install-root>/scripts/agent-workflow-check.py`. If neither, stop and tell the developer. |
| 4.3 | `scripts/format-verdict-comment.py` | Copy `<install-root>/scripts/format-verdict-comment.py`. The CI workflow step `Format verdict for PR comment` invokes it. |
| 4.3 | `scripts/agent-redline-report.py` | Copy `<install-root>/agent-redline/scripts/agent-redline-report.py`. |
| 4.3r | `scripts/agent-workflow-runtime.py`, `.sh`, `.ps1` | Copy all three runtime adapters. Structured file mutations use the shared guard; shell mutations bypass it and remain covered by final-artifact/applicability CI only. |
| 4.3h | `.claude/hooks/` + `.claude/settings.json`; `.codex/hooks.json` | Merge Claude seed/gate/reinforce hooks and Codex UserPromptSubmit/PreToolUse hooks without removing third-party hooks. Record installation and Codex project trust; do not infer mutation coverage. |
| 4.3o | `.opencode/plugins/agent-workflow.mjs` | Install the stable OpenCode 1.x plugin with its seed and structured-mutation guard; OpenCode 2 beta is outside the support claim. |
| 4.4 | root `AGENTS.md` owned reference section | Always create or reconcile only the marker-wrapped section in root `AGENTS.md`; preserve every other instruction file, surrounding prose, and third-party hooks. Existing markers are reconciled idempotently. |
| 4.5 | `.agent-redline/suppressions.yaml` | Invoke redline's Phase 4 write step. |
| 4.6 | `docs/agent-redline/skills/` | Invoke redline's Phase 4 write step. |
| 4.7 | `docs/agent-workflow/` | Copy `templates/checkpoints/` (keep the `checkpoints/` subdir) **and** `templates/skill-feedback.md` (as a sibling of `checkpoints/`) from the installed skill. Mirroring the skill's layout keeps the review-result → `../skill-feedback.md` cross-link resolvable. |
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
- Always create or reconcile only the owned marker in root `AGENTS.md`; preserve every other instruction file, surrounding prose, and third-party hooks.
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

Write `docs/agent-workflow-bootstrap-summary.md` from [`templates/bootstrap-summary.md.template`](templates/bootstrap-summary.md.template). Three named sections: Installed, Proposed, Needs human action. Record installation/trust separately from native mutation coverage; apply the native-coverage hard rule below.

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
**Skill install complete.** Confirm every file in both `.claude/skills/agent-workflow/manifest.txt` and `.agents/skills/agent-workflow/manifest.txt` exists with the recorded byte size and that the manifests match. Missing/size-mismatch means recopy from one source; do not proceed. (Do not fail on extra files.)

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
- Never infer native mutation coverage from installation, trust, or direct evaluator success. Verified requires a denied native operation with unchanged target and records runtime version, execution surface, and tool; otherwise record degraded.

## When the repo doesn't fit

If Phase 1 finds no recognizable structure to protect — no source code, no architecture to classify, no PRs as the dominant flow — escalate. Bootstrap protects boundaries the team is willing to name. A repo with nothing to protect doesn't benefit; suggest the developer reconsider.

If the developer wants to proceed anyway, bootstrap with `redline:` covering only what does exist (security paths if any, runtime config, migrations). Don't fabricate architecture the codebase doesn't have.
