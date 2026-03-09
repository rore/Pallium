# Semantic Baseline

## Current Baseline

Recorded on: 2026-03-09

Chosen path:

- provider: `openai_compatible`
- model: `gpt-5-mini`
- prompt variant: `strict_decision_v2_source_aware`
- prompt schema id: `typed_memory_extraction`
- prompt schema version: `v3`
- run id: `semantic-regression__openai-compatible__gpt-5-mini__20260309t173639z`

## Metrics

Committed regression batch:

- total items: `30`
- succeeded: `30`
- failed: `0`
- overall correct: `27 / 30`

Promoted counts:

- `decision`: `11`
- `investigation_outcome`: `12`
- `discussion_summary`: `7`

Per-type metrics:

- `decision`
  - expected: `10`
  - predicted: `11`
  - correct: `10`
  - false positives: `1`
  - false negatives: `0`

- `investigation_outcome`
  - expected: `10`
  - predicted: `12`
  - correct: `10`
  - false positives: `2`
  - false negatives: `0`

## Known False Positives

Current false positives in the committed batch:

1. `discussion-003`
   - text: `The team agreed that we need a clearer operator playbook for export incidents.`
   - predicted: `decision`

2. `discussion-004`
   - text: `Export lag increased after the broker restart, and we should watch it closely tonight.`
   - predicted: `investigation_outcome`

3. `discussion-006`
   - text: `A backlog spike was detected on the export topic after the maintenance window.`
   - predicted: `investigation_outcome`

## Run Command

```powershell
.\.venv\Scripts\python.exe -m evals.semantic_runner --suite-name semantic-regression --max-concurrency 4
```
