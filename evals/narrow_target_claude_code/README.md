# Narrow-Target Eval — Claude Code on this Repo

**Spec:** [`docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md`](../../docs/specs/2026-07-01-narrow-target-claude-code-in-pallium-repo.md)

Seven scenarios (5 positive + 2 negative) measured against Pallium as
live on `main`. Every PR in the milestone re-runs this suite and posts
a delta in the PR body.

## Measures

**candidate-recovery, injection-precision, downstream-task-effect** — this
suite reports **injection-precision and specificity**. It is not a
candidate-recovery eval.

## Layout

- `scenario_XX_*.py` — one runnable per scenario. Returns
  `{"verdict": "PASS"|"FAIL"|"INCOMPLETE", "precision": float,
   "specificity": float, "timing": str, "type_distribution": {...},
   "diagnostic": str}`.
- `run_all.py` — invokes each scenario, aggregates, writes the
  baseline JSON.

## Usage

```bash
# Run one scenario:
PYTHONPATH=".local/test-env/site-packages;." \
  "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe" \
  -m evals.narrow_target_claude_code.scenario_01_repeat_failed_command

# Run all scenarios and write baseline JSON:
PYTHONPATH=".local/test-env/site-packages;." \
  "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe" \
  -m evals.narrow_target_claude_code.run_all \
  --output evals/narrow_target_claude_code/baseline_2026-07-01.json
```

## Status

- 2026-07-01: skeletons landed; all scenarios return `INCOMPLETE` (no
  fixtures wired yet). Fixture wiring lands in Week 2 per milestone plan.

## What INCOMPLETE means

The scenario runner runs, but the fixture that constructs Session A's
canned state hasn't been wired to Pallium's ingest API yet. This is
deliberate — the spec was drafted before implementation started.
Progressive fixture wiring in Week 2.
