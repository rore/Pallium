# CLAUDE.md

## Project

Pallium — local-first memory sidecar for AI agents. Python 3.12+, FastAPI, SQLite.

## Execution Discipline

Follow `tools/execution-loop/SKILL.md` for any non-trivial change (3+ steps, behavior risk, refactor).

## Required Reading

Always read before any work:

- `AGENTS.md` — repo-level non-negotiables and delegation rules
- `tools/execution-loop/SKILL.md` — execution workflow

Read on demand:

- `tools/pallium-architect-review/SKILL.md` — when reviewing, shaping, or coordinating work
- `agent-policy.yaml` + `AGENTS.md` "agent-redline" section — when classifying a change before editing (red/blue/gray + watch); see `docs/agent/` for per-checkpoint guidance
- `minimap-roadmap` skill — when touching `roadmap/` files; invoke via the Skill tool, lives at `.claude/skills/minimap-roadmap/`

## Context Sources

Read when needed, not upfront:

- `docs/context/architecture.md` — when checking implementation details or boundary questions
- `docs/context/decisions.md` — when verifying a specific accepted decision or rationale
- `docs/context/state.md` — when checking current test/pipeline state
- `docs/context/lessons.md` — when debugging a problem that might have a known solution
- `docs/context/validation.md` — **read before proposing any new eval** — has an Eval Toolbox table mapping intent to existing tool. The repo has 80+ eval scripts and most "would change X have helped" questions are already covered by `evals/anchor_probe/thread_replay.py`, `evals/live_value_scenarios/`, or `evals/validation_runner.py`.
- `roadmap/board.md` — when doing roadmap or prioritization work

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

# Run exploratory QA invariant runner (seed scenarios)
python -m evals.generated_exploratory.invariant_runner

# Run exploratory QA with parallel workers and LLM cache
python -m evals.generated_exploratory.invariant_runner --workers 4 --cache-dir .local/llm-cache

# Run fact consolidation retrieval quality eval
python -m evals.fact_consolidation_eval

# Generate exploratory QA scenarios from taxonomy
python -m evals.generated_exploratory.generator --high-risk-only --count 1 --output evals/generated_exploratory/scenarios/batch.json
```

## Local Config

- `pallium.local.toml` — package/provider structure
- `.env.local` — secrets and one-off overrides
