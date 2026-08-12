# AGENTS.md

Treat `roadmap/` as the canonical repo-local roadmap workspace for humans and agents.
Use `docs/context/` for broader design context, but keep roadmap state and queue changes in the minimap files.

Repo-level non-negotiables:

- use `README.md`, `docs/context/*`, relevant `docs/designs/*`, and `roadmap/*` as the source of truth
- **honor the two invariants at the top of [`docs/context/lessons.md`](docs/context/lessons.md)** on every retrieval / ranking / eval PR: (1) retrieval alone never updates accessibility state — verified downstream use only; (2) every eval number states whether it measures candidate-recovery, injection-precision, or downstream-task-effect
- **every feature ships with end-to-end coverage of all edge cases.** A feature is not done when the happy path works; it's done when every boundary (empty / max / over-max), every error path (missing entity, invalid enum, state conflict, permission), every state interaction (idempotence, cross-state combinations, chain length > 2), every locale (unicode, non-ASCII), and every full-lifecycle journey (create → mutate → dispose) has an E2E test asserting the observable contract. Unit + integration tests alone don't discharge this — an E2E test drives through the same surface the caller uses (HTTP, MCP, hook) and asserts state through the same read path (list endpoint, retrieval, audit). See `tests/test_w3_memory_writes_e2e.py` for the reference shape.
- optimize for the smallest valuable slice that strengthens the current product claim
- protect the generic core, reusable capability, and package-specific semantic boundaries
- call out roadmap, docs, and code drift explicitly before endorsing a change
- treat concrete downstream incidents as bug sources, but generalize fixes into reusable memory-system capabilities before proposing roadmap or implementation work
- avoid proposing or implementing scenario-specific features keyed to product names, tool names, ticket ids, or one-off phrasing unless the work is explicitly integration-scoped
- keep new tests, fixtures, replay assets, and benchmark cases anonymized and domain-generic by default
- translate scenario-specific reproductions into generalized retrieval, routing, packaging, lifecycle, compatibility, or benchmark failure classes before defining the work
- delegated work is not complete until it has been reviewed, findings have been addressed, and roadmap/docs have been aligned when the feature status changed
- if `apply_patch` fails because of sandbox or environment limitations on this machine, delegated workers may use the smallest deterministic local file-write fallback and must report that fallback explicitly

Testing and eval conventions: see `docs/testing-conventions.md`.

---

<!-- agent-workflow:agents-section:start -->
# agent-workflow

This repository uses [agent-workflow](https://github.com/rore/agent-workflow) — a workflow harness for engineering tasks. Bundled with agent-redline for path-based risk classification.

**Where things live:**

| Path | What |
|---|---|
| `agent-workflow.yaml` | Per-repo config. Edit cautiously. |
| `agent-redline-policy.yaml` | Per-repo redline policy (zones, boundaries, checkpoints). Architecture-review required. |
| `.agent-redline/suppressions.yaml` | Suppression markers for redline. |
| `.agent-workflow/tasks/<slug>.md` | One Work Record per task / branch. Slug derives from branch name. |
| `scripts/agent-workflow-check.py` | Vendored CI checker. |
| `scripts/agent-redline-report.py` | Vendored redline reporter. |
| `docs/agent-workflow/` | Per-checkpoint reference docs. |
| `docs/agent-redline/skills/` | Redline's per-checkpoint reference docs. |
| `.github/workflows/agent-workflow.yml` | Combined CI workflow (redline + agent-workflow gates). |
| `.claude/hooks/` | Claude Code hooks that keep the workflow engaged in plan mode (see below). |

**To start a task:** invoke the `/agent-workflow` slash command. The skill walks the checkpoints and validates the Work Record at each transition.

**Plan mode:** when you produce an implementation plan for a change that touches a **guarded path** (configured in `agent-workflow.yaml` under `hooks.guardedPaths`; defaults to `src/`), the plan's **first implementation step must be** *"Invoke the `/agent-workflow` skill to create the Work Record and classify risk, before any code edit."* On approval, do that step first, before editing any guarded file. A repo hook (`.claude/hooks/check-plan.sh`) validates this at plan-approval time; it is a nudge, not a substitute for the CI gate.

**Local check before pushing:**

```bash
python scripts/agent-workflow-check.py --repo-root . --slug <slug>
```

Exit codes: `0` clean, `1` advisory, `2` blocking. CI runs the same check on PR open and posts a sticky verdict comment.

**Re-bootstrap:** delete `agent-workflow.yaml` and re-run `/agent-workflow`. The skill detects the absence and walks the install conversation.
<!-- agent-workflow:agents-section:end -->

### Known import-graph smells (not enforced as layer contracts)

These are real cross-layer couplings the code lives with today. One is **tripwired** in `pyproject.toml` via `ignore_imports` — adding a second offender fails CI. The rest are gated by red-zone classification on the relevant files. Captured here so the analysis isn't re-derived later:

- **`storage.sqlite_workstream → capabilities.workstreams`** — storage owning a capability-shaped store. Tripwired (one baselined import).
- **`core ↔ semantic` peer tangle** — `core/{service,routing,query,processing,consolidation_runner}.py` import from `semantic`; `semantic` imports `core.models` and `core.contracts`. Not enforceable as a `layers` contract; gated via red-zone on the relevant `core/*` files.
- **`core → capabilities`** — `core/consolidation_runner.py` and `core/service.py` import `capabilities.*`. Deliberate orchestration coupling, not an accident; gated via red-zone on those `core/*` files.

