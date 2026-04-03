# AGENTS.md

Treat `roadmap/` as the canonical repo-local roadmap workspace for humans and agents.
Use `docs/context/` for broader design context, but keep roadmap state and queue changes in the minimap files.

Repo-level non-negotiables:

- use `README.md`, `docs/context/*`, relevant `docs/designs/*`, and `roadmap/*` as the source of truth
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
