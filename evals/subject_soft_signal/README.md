# subject_soft_signal — shadow re-rank replay

Counterfactual to `subject_enrichment.replay`. R2b (subject overlap as a HARD
gate) is dead — the recall cost was too steep. Open question: do enriched
subjects help when used as a **soft additive boost** instead of a gate?

This directory is offline-only. Read-only against the live DB. Zero new LLM
calls — it reuses the cached subject variants from
`evals/subject_enrichment/output/subjects_2026-05-28.jsonl`.

## Method

1. Load the three subject variants (V1 fallback / V2 deterministic / V3 LLM)
   keyed by `memory_object_id`.
2. Walk `query_audit_log` rows since `2026-05-18` whose `decision_reason`
   produced injection AND has rated feedback. In this DB the only such reason
   is `carry_forward_available` — `orientation_recency` injects but its
   `candidate_scores_json` is empty, so it cannot be re-ranked.
3. For each row:
   - Tokenize the query via `core.text.normalize_for_index`.
   - For each candidate, compute `subject_overlap = |query_tokens ∩ subject_tokens|`.
   - Per-row z-normalize `routing_score` so α is interpretable across rows.
   - If `overlap >= 2`: `boosted_score = z(routing_score) + α · log(1 + overlap)`.
   - If `overlap < 2`: `boosted_score = z(routing_score)` (no penalty — we test
     whether the signal HELPS, not whether non-overlap should be punished).
4. Baseline top-K = the candidates flagged `injected=True` in the audit row
   (production's actual selection). K = number of injected blocks for that row.
5. Boosted top-K = top-K candidates by boosted_score.
6. Compute precision / recall / decision-change-rate / promoted-vs-demoted vs
   the rated slice.
7. Sweep α ∈ {0.05, 0.10, 0.20, 0.30, 0.50} for each variant. 15 result rows.

## Run

```bash
python -m evals.subject_soft_signal.replay
```

Outputs:

- `.local/research/subject_soft_signal_replay_2026-05-28.md` — the report.
- `.local/research/_subject_soft_signal_run.md` — run log (filter decisions,
  shape examples, edge cases).
