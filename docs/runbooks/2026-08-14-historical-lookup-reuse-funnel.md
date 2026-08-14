# Runbook — Historical-Lookup Reuse Funnel (Phase-1 KPI)

**Spec:** [`docs/specs/2026-08-13-historical-lookup-measurement-contract.md`](../specs/2026-08-13-historical-lookup-measurement-contract.md)
**Loader + rollup:** [`evals/historical_lookup_measurement.py`](../../evals/historical_lookup_measurement.py)
**Retrospective judge:** [`evals/historical_lookup_judge.py`](../../evals/historical_lookup_judge.py)

## What this measures

Whether history an agent retrieved on demand (via `pallium_search_history` /
source-context expansion) was actually **reused** downstream. The KPI is a
per-rung reuse rate over eligible sessions:

- **rung-1 (incorporation)** — retrieved history verifiably appears in the
  agent's subsequent work. Observational.
- **rung-2 (influence)** — no verbatim incorporation, but the history plausibly
  shaped the work. Observational, stronger.
- **rung-3 (downstream)** — controlled/confirmed; NOT claimable from passive
  logs, so the retrospective judge never assigns it.

Every rate carries a Wilson 95% interval and the eligible-session denominator.
The output also carries a governance block: **attempted-disallowed-access
counts** over the persisted exposed sets (expected 0, computed not assumed).

## How the funnel is armed

Lookup and expansion events are persisted **unconditionally** — they do NOT
depend on `observability.query_audit_log`. A fresh `pallium service install`
seeds an `[observability]` section with `historical_lookup_funnel = true`
(the declared "armed" signal). Confirm it:

```bash
pallium service status
#   ...
#   Reuse funnel armed: yes, <N> events recorded
```

`pallium setup claude-code` also reports the funnel state during its service
verification step.

If you run your own config, ensure it includes:

```toml
[observability]
historical_lookup_funnel = true
```

## Step 1 — produce real lookups

Use an agent wired to the local service (Claude Code integration). When the
agent calls `pallium_search_history`, a `historical_lookup_reuse_event`
row (`event_type='lookup'`) is written with the exposed source ids, raw ranks,
and identity (`session_id`, `container_ref`, `trigger_origin`). A subsequent
`pallium_expand_source` writes an `event_type='expansion'` row carrying
`parent_lookup_id`.

No manual step is required — persistence is automatic once the service is
running and the agent performs lookups.

## Step 2 — run the retrospective judge (writes rung labels)

The judge samples eligible lookups, reconstructs the surrounding session turns,
and asks an LLM to label each: genuine-opportunity, rung, evidence span, and
`user_directed` vs `agent_decided`. It runs **≥3 rater seeds** over the same
sample (the rater ordinal is folded into the prompt as an inert tag so each
seed is an independent verdict, not a cache hit), writes one per-rater label
row to the append-only `historical_lookup_reuse_label` table, and reports
Cohen's κ on the double-rated subsample.

```bash
PYTHONPATH=".local/test-env/site-packages;." \
  "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe" \
  -m evals.historical_lookup_judge \
  --db ~/.pallium/data/pallium.db \
  --container-ref git:github.com/your/repo \
  --since 2026-08-01T00:00:00 \
  --seeds 0,1,2 \
  --cache-dir .local/llm-cache
```

The judge is **shadow/offline**: it only reads the write-only event table and
`source_items`, and only appends label rows. It never affects live injection or
agent output. Use `--dry-run` to reconstruct + sample contexts without any LLM
call or writes.

## Step 3 — read the KPI

The measurement loader recomputes eligible sessions, joins the labels for a
consensus rung per event, and emits the rollup:

```bash
PYTHONPATH=".local/test-env/site-packages;." \
  "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe" \
  -m evals.historical_lookup_measurement \
  --db ~/.pallium/data/pallium.db \
  --container-ref git:github.com/your/repo \
  --since 2026-08-01T00:00:00
```

Output (abridged):

```
=== Historical-Lookup Reuse Rollup ===
eligibility_n=50  n_eligible=42  n_events=17
  rung-1: verified incorporation     measures=downstream-task-effect  n=9/42  per-100=21.4  95%CI=[11.7, 35.9]
  rung-2: judged influence/necessity measures=downstream-task-effect  n=4/42  per-100=9.5   95%CI=[3.7, 22.1]
  rung-3: downstream benefit          measures=downstream-task-effect  n=0/42  per-100=0.0   95%CI=[0.0, 8.4]
  visibility violations: 0 (by_type={'cross_container': 0, 'forgotten_exposed': 0}; events=17, exposed_ids=63)
```

The rollup is **empty-data-safe**: with no eligible sessions the rates and
Wilson intervals are `null` (`note: "n/a (0 eligible)"`) rather than erroring.
Run `--dry-run` for a synthetic demo without a DB.

## Reading the numbers

- **`reuse_per_100_eligible`** — reuse events per 100 eligible sessions, per
  rung. Deduplicated per session per rung.
- **`wilson_95`** — 95% confidence interval on the rate; wide intervals mean the
  window is too small to conclude anything.
- **`visibility_violations`** — counts of exposed source ids whose scope did not
  match (`cross_container`, `forgotten_exposed`). Expected `0`; a non-zero value
  means a redaction/gate regression leaked a forbidden id into the exposed set
  and must be investigated.
- **Cohen's κ** (from the judge report) — inter-rater agreement on the rung
  labels. Low κ means the rung labels are noisy; treat the rates as soft.
