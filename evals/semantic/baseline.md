# Semantic Baseline

## Current Baseline

Recorded on: 2026-03-09

Chosen path:

- provider: `openai_compatible`
- model: `gpt-5-mini`
- prompt variant: `strict_typed_memory_v4_evidence_guarded`
- prompt schema id: `typed_memory_extraction`
- prompt schema version: `v4`
- run id: `semantic-regression-compare__openai-compatible__gpt-5-mini__20260309t183600z`

## Metrics

Committed regression batch:

- total items: `30`
- succeeded: `30`
- failed: `0`
- overall correct: `30 / 30`

Promoted counts:

- `decision`: `10`
- `investigation_outcome`: `10`
- `turn_summary`: `10`

Per-type metrics:

- `decision`
  - expected: `10`
  - predicted: `10`
  - correct: `10`
  - false positives: `0`
  - false negatives: `0`

- `investigation_outcome`
  - expected: `10`
  - predicted: `10`
  - correct: `10`
  - false positives: `0`
  - false negatives: `0`

## Comparison Note

On the same 30-item batch and model, `strict_decision_v2_source_aware` scored `27 / 30`, while `strict_typed_memory_v4_evidence_guarded` scored `30 / 30`. The improvement came from combining stronger prompt instructions with code-side evidence gating on typed-memory promotion.

## Run Command

```powershell
.\.venv\Scripts\python.exe -m evals.semantic_runner --suite-name semantic-regression --max-concurrency 4 --prompt-variants strict_typed_memory_v4_evidence_guarded
```
