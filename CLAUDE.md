# CLAUDE.md

## Project

Pallium — local-first memory sidecar for AI agents. Python 3.12+, FastAPI, SQLite.

## Required Reading

Before any work, read and follow:

- `AGENTS.md` — repo-level non-negotiables, skill routing, and delegation rules
- `tools/execution-loop/SKILL.md` — execution workflow (plan, execute, verify, close)
- `tools/pallium-architect-review/SKILL.md` — architect review workflow (use when reviewing, shaping, or coordinating work)
- `tools/minimap/SKILL.md` — roadmap file conventions (use when touching `roadmap/`)

## Context Sources

- `docs/context/architecture.md` — stable architecture truths
- `docs/context/decisions.md` — accepted decisions
- `docs/context/state.md` — current repo state
- `docs/context/lessons.md` — problem-solution pairs
- `roadmap/board.md` — current queue and priorities

## Commands

```bash
# Run tests
python -m pytest tests/ -x -q

# Run specific test slice
python -m pytest tests/test_visibility_scope.py -x -q

# Start server
python -m app.run serve --host 127.0.0.1 --port 8000

# Run agent simulation harness
python -m app.agent_simulation
```

## Local Config

- `pallium.local.toml` — package/provider structure
- `.env.local` — secrets and one-off overrides
