# AGENTS.md

For roadmap planning and roadmap file updates in this repo, follow `tools/minimap/SKILL.md`.
For architecture review, feature shaping, and cross-thread coordination, follow `tools/pallium-architect-review/SKILL.md`.

Treat `roadmap/` as the canonical repo-local roadmap workspace for humans and agents.
Use `docs/context/` for broader design context, but keep roadmap state and queue changes in the minimap files.

Repo-level non-negotiables:

- use `README.md`, `docs/context/*`, relevant `docs/designs/*`, and `roadmap/*` as the source of truth
- optimize for the smallest valuable slice that strengthens the current product claim
- protect the generic core, reusable capability, and package-specific semantic boundaries
- call out roadmap, docs, and code drift explicitly before endorsing a change
