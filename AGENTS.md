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

## agent-redline

This repo uses [agent-redline](https://github.com/rore/agent-redline). Before making changes:

1. Read `agent-policy.yaml`.
2. Classify your intended change as blue / red / gray (see `docs/agent/`), and note any `watch` paths touched — those are surfaced in the PR comment regardless of the primary classification.
3. Refuse to work around boundary rules. Fix the structure or escalate.

Per-checkpoint guidance lives in `docs/agent/`. Read the file matching the situation:

- `blue-zone-work.md` — autonomous work
- `red-zone-change.md` — architectural change
- `gray-zone-change.md` — unclassified path
- `boundary-violation.md` — the boundary backend reported a forbidden import
- `pr-discipline.md` — PR shape and description rules
- `api-change-checkpoint.md`, `persistence-change-checkpoint.md`, `security-change-checkpoint.md` — when those checkpoints apply

Run the local check before pushing:

```bash
./scripts/agent-redline-check.sh
```

### Known import-graph smells (not enforced as layer contracts)

These are real cross-layer couplings the code lives with today. One is **tripwired** in `pyproject.toml` via `ignore_imports` — adding a second offender fails CI. The rest are gated by red-zone classification on the relevant files. Captured here so the analysis isn't re-derived later:

- **`storage.sqlite_workstream → capabilities.workstreams`** — storage owning a capability-shaped store. Tripwired (one baselined import).
- **`core ↔ semantic` peer tangle** — `core/{service,routing,query,processing,consolidation_runner}.py` import from `semantic`; `semantic` imports `core.models` and `core.contracts`. Not enforceable as a `layers` contract; gated via red-zone on the relevant `core/*` files.
- **`core → capabilities`** — `core/consolidation_runner.py` and `core/service.py` import `capabilities.*`. Deliberate orchestration coupling, not an accident; gated via red-zone on those `core/*` files.

