# workstream_consolidation eval

Re-runs the offline T1.7 consolidation re-key dry-run on the live
production DB using the in-repo workstream cascade (Phase 4A, design 014).

Reproduces the offline finding (1014 → 1153 atomic_fact groups,
+13.7% on the self-referential slice) within ±10% as a regression guard.

## Run

```bash
python -m evals.workstream_consolidation.audit
```

Optional:

- `--db PATH` — override the live DB path (default
  `~/.pallium/data/pallium.db`)
- `--output DIR` — override the report directory
  (default `.local/research/`)
- `--baseline-old N` / `--baseline-new N` — override the offline baseline

This eval is operator-runnable, not pytest-runnable.
