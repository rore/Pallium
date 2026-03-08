# Project Context

This directory holds the stable project context for `Pallium`.

Use it for broader design intent and accepted architectural direction.

## Purpose

Use this folder to store:

- project vision and scope
- accepted architectural direction
- important decisions and open design questions
- repo state that is useful for implementation handoff

`roadmap/` is the canonical planning workspace for queue, ordering, phases,
status, and parked ideas.

## File Map

- `vision.md`
  What Pallium is, is not, and the core principles that should remain stable.

- `architecture.md`
  The current top-level architecture of the system.

- `decisions.md`
  Short running log of important accepted decisions and open architectural
  questions.

- `state.md`
  Repo and implementation-handoff state that is useful across sessions.

## Conventions

- Keep these files short and high-signal.
- Prefer `roadmap/` for planning state and queue changes.
- Prefer `docs/designs/` for fuller design threads, tradeoffs, and analyses.
- Update `decisions.md` when a design thread becomes accepted project direction.
