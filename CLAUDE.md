# CLAUDE.md

## Project

Pallium — local-first memory sidecar for AI agents. Python 3.12+, FastAPI, SQLite.

## Execution Discipline

Every non-trivial change (3+ steps, behavior risk, refactor) must follow this loop:

1. **Plan** — write a checkable execution plan before coding
2. **Review your plan** — check it yourself as the architect: smallest change? preserves contracts? fits boundaries?
3. **Ensure regression coverage** — if the code you're changing lacks tests, add them first and commit separately
4. **Execute** — implement the minimal change
5. **Review your implementation** — review your own diff for correctness, edge cases, unnecessary complexity. Use a subagent for large changes.
6. **Verify** — run tests. Prefer evidence over reasoning from inspection.
7. **Close** — summarize what changed, what was verified, residual risk.

If an assumption breaks mid-execution, stop and re-plan. Full details: `tools/execution-loop/SKILL.md`.

## Required Reading

Before any work, read and follow:

- `AGENTS.md` — repo-level non-negotiables, skill routing, and delegation rules
- `tools/execution-loop/SKILL.md` — execution workflow (full details of the loop above)
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

# Clean all runtime data (DB + vector index) for fresh start
bash scripts/clean-data.sh

# Start server
python -m app.run serve --host 127.0.0.1 --port 8000

# Run agent simulation harness
python -m app.agent_simulation
```

## Local Config

- `pallium.local.toml` — package/provider structure
- `.env.local` — secrets and one-off overrides
