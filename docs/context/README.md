# Project Context

This directory holds the stable project truth for Pallium.

Use it for:

- vision and identity
- accepted top-level architecture
- durable decisions
- lightweight implementation handoff state
- important problems and solutions worth remembering across sessions

For broader docs ownership, see ../README.md.

## File Map

- vision.md
  What Pallium is, is not, and the principles that should remain stable.

- architecture.md
  The current accepted top-level system shape.

- decisions.md
  Accepted decisions plus the small set of open architectural questions that
  still need explicit treatment.

- state.md
  Small repo and handoff snapshot. Not a queue or planning document.

- strategy-vnext.md
  Session History direction, evidence, experiments, and ordered foundation work.

- lessons.md
  Durable notes about important implementation problems, debugging traps, and
  the solutions or operating rules that should not be rediscovered.

- prompt-improvement.md
  The repo workflow for adding prompt variants, running bakeoffs, and choosing
  new defaults for live semantic prompt roles.

- validation.md
  Benchmark architecture, acceptance gates, dataset tiers, and operational
  metrics.

## Conventions

- Keep these files short and high-signal.
- Put queue, sequencing, and phase status in roadmap/.
- Put deeper proposals and tradeoffs in docs/designs/.
- If a problem/solution pair is likely to save future debugging time, record it in lessons.md.
