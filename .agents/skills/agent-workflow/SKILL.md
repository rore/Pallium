---
name: agent-workflow
description: Use when starting, advancing, pausing, or resuming an engineering task. Maintains the Work Record, validates readiness gates between checkpoints, and routes risk classification to agent-redline (bundled, required by default).
---

# agent-workflow

Drive engineering tasks through a small set of checkpoints. The harness records what you do in a structured Work Record so the next agent or reviewer can pick up where you stopped. Plan quality, discovery sufficiency, implementation correctness, evidence adequacy — those stay reviewer judgments; you produce the artifacts that make them possible.

## Pick a mode

1. **`agent-workflow.yaml` exists in the repo root** → read [`operating-mode.md`](operating-mode.md). Everyday work.
2. **User asked you to set up `agent-workflow` on this repo** → read [`bootstrap-mode.md`](bootstrap-mode.md). One-shot install.
3. **Neither** → this skill is not relevant.

Read only the file for the mode that applies.

## Principles

- **Gate applicability first.** Unless it exempts the whole change, write the Work Record before touching code.
- **Shape is derived from `(Risk, Complexity)`.** `(Routine, Simple)` → compact. Anything else → expanded. Checker enforces via `workrecord.shape_matches_classification`.
- **Stay within recorded scope.** Material scope expansion returns the task to planning.
- **Update State at transitions.** `Ready to implement` → `Ready for review` only when verification passes.
- **Pause on assumption failure.** Stop and update the assumption + affected fields. Do not continue under stale assumptions.
- **Marker block is the structured surface.** Prose around it is human notes. Don't put structured state outside the markers; don't put free prose inside them.
- **Report upstream defects.** If product/skill behavior fails, contradicts guidance, or forces a consequential guess, load [`templates/skill-feedback.md`](templates/skill-feedback.md). Review the Result is the final catch.

## Decision priority

When ambiguous: repo's `agent-workflow.yaml` → repo's `AGENTS.md`/`CLAUDE.md` → mode-specific skill file → these principles → ask the developer. Do not invent rules the config does not state.

## Resources (load on demand)

- `operating-mode.md` — when entering operating mode.
- `bootstrap-mode.md` — when entering bootstrap mode.
- `templates/checkpoints/*.md` — per-checkpoint, load only when entering that checkpoint.
- `templates/skill-feedback.md` — load only when a trigger from the Skill-feedback check fired.
- The repo's `agent-workflow.yaml` — once on pickup, to learn the configured `taskPath`.
