# injection_policy_2026_06

Reproducible Phase 0 snapshot for the abstention-policy plan in
[`docs/specs/2026-06-27-injection-policy-abstention.md`](../../docs/specs/2026-06-27-injection-policy-abstention.md).

## Run

```bash
# Phase 0 — snapshot (no holdout)
python -m evals.injection_policy_2026_06.analyze
python -m evals.injection_policy_2026_06.analyze --output report.json

# Phase 1 — chronological 80/20 holdout
python -m evals.injection_policy_2026_06.holdout
python -m evals.injection_policy_2026_06.holdout --output report.json
python -m evals.injection_policy_2026_06.holdout --db /path/to/pallium.db --quiet

# Phase 2a — approximate historical decision replay (audit-only)
python -m evals.injection_policy_2026_06.decision_replay
python -m evals.injection_policy_2026_06.decision_replay --output report.json

# Phase 6 — measurement-window rollups (requires Phase 0.5+4+5b live data)
python -m evals.injection_policy_2026_06.phase6_measurement
python -m evals.injection_policy_2026_06.phase6_measurement --since 2026-07-04
```

Reads the local Pallium SQLite database in read-only mode. Defaults to
`~/.pallium/data/pallium.db`. Joins `memory_feedback` to
`query_audit_log` on `(memory_object_id, query_audit_log_id)`.

## What it reports

- Per-container bad-injection rate (relevant vs not_relevant).
- Per-type score distribution (block score) and per-type coverage counts.
- Precision/recall frontier per type and the lowest threshold that
  reaches the spec's 70% precision target.
- The proposed-policy precision/recall/bad-elimination headline numbers.
- A sanity-check report applying the same thresholds to `routing_score`
  to confirm `score` (the injected-block result score) is the correct
  field to gate on.

## Committed snapshots

- `snapshot_2026-06-27.json` — Phase 0 reference output backing the
  spec's all-data headline numbers. Regenerate when those numbers move.
- `holdout_2026-06-27.json` — Phase 1 chronological 80/20 holdout
  validation. The spec's binding pass-bar numbers come from this file,
  not from Phase 0.
- `decision_replay_2026-06-27.json` — Phase 2a approximate historical
  decision-simulation replay. Audit-trail artifact only; gates on
  `routing_score` because historical rows lack the result `score` field.

```bash
python -m evals.injection_policy_2026_06.analyze \
    --output evals/injection_policy_2026_06/snapshot_2026-06-27.json \
    --quiet
python -m evals.injection_policy_2026_06.holdout \
    --output evals/injection_policy_2026_06/holdout_2026-06-27.json \
    --quiet
python -m evals.injection_policy_2026_06.decision_replay \
    --output evals/injection_policy_2026_06/decision_replay_2026-06-27.json \
    --quiet
```

Ad-hoc re-runs should write to `.local/research/` instead of overwriting
the committed snapshots.

## Tests

- `tests/test_injection_policy_2026_06_analyze.py` — Phase 0 pure
  compute layer (15 tests).
- `tests/test_injection_policy_2026_06_holdout.py` — Phase 1 dedup,
  chronological split, min-N threshold rule, holdout evaluation,
  disposition logic, recommended-policy assembly (23 tests).
- `tests/test_injection_policy_2026_06_decision_replay.py` — Phase 2a
  candidate parsing, type-allowlist + threshold + top-K simulation,
  variant comparison, divergence diagnostics (21 tests).
- `tests/test_injection_policy_2026_06_phase3a.py` — Phase 3a config
  + gate semantics (28 tests).
- `tests/test_injection_policy_2026_06_phase4.py` — Phase 4
  trigger_origin validation + gate-bypass semantics (30 tests).
- `tests/test_injection_policy_2026_06_phase5.py` — Phase 5a
  memory_usage_audit schema, storage, service, endpoints (16 tests).
- `tests/test_injection_policy_2026_06_phase6.py` — Phase 6
  measurement rollups (9 tests).

Tests use in-memory fixtures. Live-DB headline numbers belong in the
committed snapshot JSONs, not in tests.
