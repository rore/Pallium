# Project Context

This directory holds the stable working context for `Pallium`.

It exists to keep the project direction explicit while the codebase is still
small and evolving quickly.

## Purpose

Use this folder to store:

- current project intent
- architectural direction that is currently accepted
- active decisions
- open questions
- current implementation state

For fuller design threads, proposals, and analyses, use `docs/designs/`.

## File Map

- `vision.md`
  The product and architecture intent. What Pallium is, is not, and the core
  principles that should remain stable.

- `architecture.md`
  The current top-level design of the system.

- `decisions.md`
  Short running log of important decisions and why they were made.

- `ideas.md`
  Raw ideas worth keeping, but not yet accepted as current design.

- `state.md`
  Current repo/project state so implementation work can resume with less
  re-discovery.

- `roadmap.md`
  Current expected phases and near-term priorities.

## Conventions

- Keep entries short and high-signal.
- Prefer updating these files over repeating the same design context in chat.
- Record decisions when they affect the shape of the core, plugin model, API,
  storage, or retrieval behavior.
- Treat `vision.md` as stable intent and `state.md` as volatile working notes.
