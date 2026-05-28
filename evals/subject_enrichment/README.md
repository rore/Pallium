# subject_enrichment

Offline experiment: re-evaluate the proposed R2b gate (subject token overlap
with query >= 2) using **real subjects** rather than the body-text fallback
that the production extractor currently emits.

`memory_objects.subject` is NULL for every active non-fact memory type
since 2026-05-18. Production reads via `core.subject.subject_text_for_payload`
which falls back to the FULL body. So R2b's previously-validated numbers
(P 0.42→0.52, R 0.81) measured **body overlap**, not topic overlap. We need
to know whether real subjects would change R2b's P/R, or whether the gate
behaves the same regardless.

## What this does (read-only)

1. `enrich.py` walks the production DB and produces a candidate subject for
   each active memory under three variants:
   - **V1 payload_fallback**: `subject_text_for_payload(type, payload)` — the
     production baseline.
   - **V2 deterministic**: payload-aware extraction. Looks at
     `subject_hints`, `topic`/`topic_label`/`tags`/`anchors`,
     `retrieval_enrichment.retrieval_context`, then falls through to a per-
     type first-noun-phrase head. Falls back to V1 when nothing extracts.
   - **V3 LLM**: Claude Sonnet via the production proxy
     (`hai_anthropic` / `anthropic--claude-sonnet-latest`), prompted to
     emit a 5-10 word noun phrase. Cached on disk under
     `.local/llm-cache/subject_enrichment/`.

   Output: `evals/subject_enrichment/output/subjects_2026-05-28.jsonl`,
   one JSON row per memory.

2. `replay.py` walks `query_audit_log` since 2026-05-18, takes every
   *injected* candidate, and applies the R2b gate (overlap >= 2) using each
   variant's subject. Cross-references KEEP/DROP against the
   `memory_feedback` ratings linked to the same audit row, then emits
   precision / recall / drop rate / false-skip rate per variant.

   Output: `.local/research/subject_enrichment_replay_2026-05-28.md`.

## Run

```bash
python -m evals.subject_enrichment.enrich
python -m evals.subject_enrichment.replay
```

`enrich.py` accepts `--no-llm` (skip V3 — use V2 as the V3 value) and
`--limit-llm N` (cap LLM calls; remaining rows fall through to V2). All
LLM responses are cached so re-runs cost nothing.

## Constraints

- No production code changes. All logic lives in this folder.
- No DB writes. Read-only access to `~/.pallium/data/pallium.db`.
- Failure to reach the LLM proxy is logged; V3 falls back to V2 silently
  per row, and the run-log records the count.
- A run-log of edge cases / errors is appended to
  `.local/research/_subject_enrichment_run.md`.
