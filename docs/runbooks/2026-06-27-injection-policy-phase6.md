# Phase 6 Runbook — Injection-Policy Measurement Window

**Spec:** [`docs/specs/2026-06-27-injection-policy-abstention.md`](../specs/2026-06-27-injection-policy-abstention.md)
**Script:** [`evals/injection_policy_2026_06/phase6_measurement.py`](../../evals/injection_policy_2026_06/phase6_measurement.py)

## Goal

After ~4 weeks of live data with Phase 3a/3b/4/5 deployed, decide
whether to:

- **Hold** the policy as-is.
- **Tighten** thresholds (or expand demotions).
- **Delete** on-demand types that are never triggered.
- **Revisit** the abstention thesis entirely if precision regressed.

## Preconditions

Before running the measurement:

- [ ] Phase 0.5 candidate-snapshot instrumentation (`score` +
      `retrieval_source` in `candidate_scores_json`) has been live for
      the full window.
- [ ] Phase 3a config in `pallium.local.toml` reflects the demotion
      target (`investigation_outcome` / `thread_summary` →
      `on_demand`; `fact_summary` → `suspended`; `task_checkpoint` →
      `event`).
- [ ] Phase 4 hook scripts deployed and registered:
      `python -m app.run setup claude-code`.
- [ ] Phase 5b populator hook is running and filling
      `memory_usage_audit.referenced_in_next_turn`. If not, the
      `usage_rate` numbers will be `None`; only `rating_precision`
      from `memory_feedback` will be meaningful.

## Run

```bash
PYTHONPATH=".local/test-env/site-packages;." \
  "C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13-windows-x86_64-none/python.exe" \
  -m evals.injection_policy_2026_06.phase6_measurement \
  --since 2026-07-04T00:00:00 \
  --output evals/injection_policy_2026_06/phase6_<DATE>.json
```

(Adjust `--since` to the window start; replace `<DATE>` with the run
date.)

## Read the output

The script emits three rollups:

### 1. Per-type proactive precision

Looks at every injection where `trigger_origin IS NULL` (proactive
default queries). For each `memory_type`:

- `n_total` — how many proactive injections of this type.
- `n_populated` — how many had a Phase 5b populator decision.
- `usage_rate` — fraction of populated rows where the agent
  referenced the memory in its next turn. **This is the new precision
  metric the spec asks for.**
- `n_rated_relevant`, `n_rated_bad`, `rating_precision` — the older
  human-rating-based metric (Phase 1 baseline).

### 2. Per-trigger usage

Breaks down rates by `trigger_origin`, including the proactive
default. Use this to catch:

- Triggers that fire often but produce 0% usage → retire the trigger.
- Triggers that never fire → unreachable trigger condition; revisit.

### 3. Demoted-type discovery

For each Phase 3b-demoted type, how often it was retrieved via a
trigger vs proactively. A type with zero triggered retrievals over
the full window is a candidate for permanent deletion.

## Decision matrix

| Observation | Action |
|---|---|
| Proactive `usage_rate` ≥ 50% for `constraint_memory`/`decision`, ≥ 70% rating_precision | Hold the policy. |
| Proactive `usage_rate` < 30% | Tighten — either raise the threshold (config edit) or move the type to on-demand. |
| Proactive `usage_rate` regressed vs Phase 1 baseline rating_precision | Review the 5b matcher heuristic — possibly false negatives. |
| On-demand type has zero triggered retrievals in the window | Delete the type from extraction (separate spec). |
| Trigger has 0% usage_rate | Disable the trigger in the hook (`post_tool_use.py`, `session_start.py`) or raise its threshold (e.g. retry count ≥ 5 instead of 3). |
| `usage_rate` is consistently `None` (no populated rows) | Phase 5b populator is broken or not running — debug the Stop hook first. |

## Sample-size guardrails

Trust a cell only when `n_populated >= 30` (or `n_rated >= 30` for the
rating metric). Below that, the rates are noise. The script does NOT
mark cells as insufficient — judgment is on the analyst.

## After the decision

- If holding/tightening: commit a TOML diff to the recommended
  config in `pallium.example.toml` so future installs land on the
  validated values.
- If deleting on-demand types: open a separate spec for retiring the
  extraction path. Do NOT delete data; suspend the extractor.
- If the abstention thesis was wrong (the proactive default
  out-performed the demoted types post-Phase 5b): revisit the spec
  Phase 3b config and consider rolling back to a broader proactive
  set.

Always commit the measurement JSON next to the spec for the audit
trail:

```bash
git add evals/injection_policy_2026_06/phase6_<DATE>.json
git commit -m "Phase 6 measurement window: <DATE>"
```

## 2026-07-23 baseline + scheduled window

After the delivery-path fixes merged to main (`6d1d190` failure-trigger
field, `0198a78` git-grounded orientation), a **day-0 baseline** was
captured:

```
evals/injection_policy_2026_06/phase6_measurement_2026-07-23_baseline.json
```

Baseline read (since 2026-06-27, n_usage_rows=115, n_feedback=691):
`session_start_orientation` now fires (8 rows, up from 0 pre-fix) but
usage is not yet populated; `post_tool_failure` / `retry_threshold`
still show no rows. This is expected — the fixes are days old. The real
read needs the ~2-week window.

**Scheduled window (~2026-08-06).** Re-run with the window start pinned
to the fix-merge date so the numbers reflect post-fix behavior only:

```bash
python -m evals.injection_policy_2026_06.phase6_measurement \
  --since 2026-07-23 \
  --output evals/injection_policy_2026_06/phase6_measurement_2026-08-06.json
```

Check: did the dead triggers move off zero, and did injected memories
get used next-turn (usage_rate populated)?

## Companion: re-admission opportunity (under-injection)

A separate finding (`docs/investigations/2026-07-22-task-trace-cross-session-value.md`)
showed the abstention gate may over-suppress on genuine user turns. Run
this **two-step, offline** measurement on the same ~Aug 6 window to size
the opportunity (no production routing change):

```bash
# 1. Judge suppressed candidates on user turns (LLM; needs PALLIUM_CONFIG_FILE + PALLIUM_HAI_API_KEY)
python -m evals.anchor_probe.underinjection_judge \
  --since 2026-07-23 --limit 150 --min-rs 300 --distinct --exclude-internal \
  --out evals/anchor_probe/underinjection_2026-08-06.md
# -> also emits underinjection_2026-08-06.jsonl

# 2. Score re-admission rules against the judge labels
python -m evals.anchor_probe.readmission_counterfactual \
  --labels evals/anchor_probe/underinjection_2026-08-06.jsonl
```

`--exclude-internal` is required — agent-internal monitoring prompts
(self-echoing "check progress" turns) otherwise dominate the sample and
mask the user-turn signal. Single-seed judge calls carry ~20pp variance
(see `docs/context/validation.md`); a follow-up may add multi-seed
consensus. This measurement gates any live re-admission change — it does
not make one.
