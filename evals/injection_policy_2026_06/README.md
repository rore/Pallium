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

```bash
python -m evals.injection_policy_2026_06.analyze \
    --output evals/injection_policy_2026_06/snapshot_2026-06-27.json \
    --quiet
python -m evals.injection_policy_2026_06.holdout \
    --output evals/injection_policy_2026_06/holdout_2026-06-27.json \
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

Tests use in-memory fixtures. Live-DB headline numbers belong in
`snapshot_2026-06-27.json` / `holdout_2026-06-27.json`, not in tests.
