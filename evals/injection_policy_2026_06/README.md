# injection_policy_2026_06

Reproducible Phase 0 snapshot for the abstention-policy plan in
[`docs/specs/2026-06-27-injection-policy-abstention.md`](../../docs/specs/2026-06-27-injection-policy-abstention.md).

## Run

```bash
python -m evals.injection_policy_2026_06.analyze
python -m evals.injection_policy_2026_06.analyze --output report.json
python -m evals.injection_policy_2026_06.analyze --db /path/to/pallium.db --quiet
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

## Committed snapshot

`snapshot_2026-06-27.json` is the committed reference output used to
back the headline numbers in the spec. Regenerate it only when those
numbers move (e.g. after Phase 1 holdout work changes the policy).

```bash
python -m evals.injection_policy_2026_06.analyze \
    --output evals/injection_policy_2026_06/snapshot_2026-06-27.json \
    --quiet
```

Ad-hoc re-runs should write to `.local/research/` instead of overwriting
the committed snapshot.

## Tests

`tests/test_injection_policy_2026_06_analyze.py` covers the pure
computation layer with in-memory fixtures — NULL `injected_blocks_json`,
missing block `score`, ratings outside the known enum, and duplicate
ratings on the same `(memory_object_id, query_audit_log_id)` pair. The
test does NOT assert against the live DB headline numbers; those belong
in `snapshot_2026-06-27.json`.
