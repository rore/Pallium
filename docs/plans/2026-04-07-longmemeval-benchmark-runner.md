# Plan: LongMemEval Benchmark Runner

## Goal

Build `evals/longmemeval_benchmark.py` — an end-to-end benchmark runner that evaluates Pallium
against the LongMemEval dataset (ICLR 2025), following the LoCoMo runner's patterns.

## Why this runner vs what already exists

| Existing | What it tests | Gap |
|----------|--------------|-----|
| External memory pressure (46 questions, oracle only) | Extraction + routing quality | No retrieval pressure, no end-to-end answer generation |
| MABench AR (300 questions, shared blob) | Long-context retrieval | No per-question isolation, SubEM not LLM-judge, no consolidation, no pipeline diagnostics |

This runner fills: per-question isolated ingestion → extraction → consolidation → retrieval → answer generation → type-specific LLM judging → pipeline diagnostics.

## Dataset

- Source: `https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned`
- Download via: `https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/{filename}`
- Default file: `longmemeval_s_cleaned.json` (~277MB, ~500 questions, ~40 sessions each)
- Also supports: `longmemeval_oracle.json` (15MB, evidence-only — upper-bound baseline)
- Download target: `evals/longmemeval/datasets/` for the `_s` variant; oracle already exists
  at `data/longmemeval/longmemeval_oracle.json` (used by the transformer tool), so
  `--variant oracle` downloads to the same `data/longmemeval/` path for consistency
- Format: JSON array, each entry has:
  - `question_id`, `question_type`, `question`, `answer`, `question_date`
  - `haystack_session_ids`, `haystack_dates`, `haystack_sessions` (list of session lists)
  - `answer_session_ids` (ground truth)
  - Each session is a list of `{"role": "user"/"assistant", "content": "...", "has_answer": true/false}`

## Data shape difference from LoCoMo

LoCoMo: N conversations × M questions per conversation. Ingest once, query many times.
LongMemEval: Each question has its own isolated haystack. 1 ingestion per question.

This means the loop is per-question, not per-conversation:
```
for question in dataset:
    create fresh DB + vector index (or load from cache)
    ingest all haystack sessions as chat messages
    drain extraction queue + reconcile vector index
    run consolidation pass (for knowledge-update detection)
    query via /query/debug
    generate answer from retrieved context
    judge answer with type-specific prompt
    trace evidence pipeline
```

## Ingestion mapping

Follow LoCoMo's `_turn_to_item` pattern. Batch size: 50 items per POST /items call
(matches LoCoMo's BATCH_SIZE and the API's MAX_ITEMS_PER_REQUEST limit).

```python
{
    "source_type": "chat_message",
    "source_id": f"{question_id}_{session_idx}_{turn_idx}",
    "content_type": "text/plain",
    "content": turn["content"],
    "role": turn["role"],
    "actor_ref": turn["role"],  # "user" or "assistant" — LongMemEval has no named speakers
    "container_ref": question_id,
    "thread_ref": f"{question_id}_{session_idx}",
    "artifact_kind": "message",
    "visibility": "public",
    "occurred_at": session_date_as_iso,  # from haystack_dates[session_idx]
}
```

Note: LongMemEval doesn't have named speakers (unlike LoCoMo's speaker_a/speaker_b),
so `actor_ref` is set to the role string directly. The existing transformer tool
(`tools/longmemeval_transformer.py`) omits `actor_ref` entirely — either approach
is functionally equivalent since `visibility: "public"` means actor-scoped personal
memory types are not created.

## Query construction

```python
{
    "text": question["question"],
    "limit": query_limit,
    "container_ref": question_id,
    "visibility": "public",
    "runtime_context": {
        "turn_kind": "new_session",
        "session_has_sufficient_local_context": False,
    },
}
```

Critical: `question_date` must be included in the answer generation prompt as `Current Date: {question_date}`.
This is load-bearing for temporal-reasoning questions.

## Type-specific judge prompts

The paper uses different judging criteria per question type. We need 5 judge variants:

1. **Standard** (single-session-user, single-session-assistant, multi-session):
   Generic generous judge similar to LoCoMo's — correct if it contains the answer or equivalent.

2. **Temporal-reasoning**:
   Same as standard + "Do not penalize off-by-one errors for number of days."

3. **Knowledge-update**:
   "If the response contains some previous information along with an updated answer, consider it correct as long as the updated answer is the required answer."

4. **Abstention** (question_id ends with `_abs`):
   "Answer yes if the model correctly identifies the question as unanswerable."

5. **Preference** (single-session-preference):
   Rubric-based — "correct if it recalls and utilizes user's personal information correctly."

Note: Abstention is a modifier (suffix `_abs`) on question_ids, not a separate question_type value.
The 6 question_type values in the data are: single-session-user, single-session-assistant,
single-session-preference, multi-session, temporal-reasoning, knowledge-update.
Mini mode picks 3 questions per type = 18 questions.

## Evidence tracing

LongMemEval annotates evidence turns with `has_answer: true`. Use this for pipeline diagnostics:

1. During ingestion, track which source_ids correspond to `has_answer: true` turns
2. After extraction, check if those source_ids produced memory objects (extraction check)
3. After retrieval, check if those memory objects appear in results (retrieval check)
4. Also track `answer_session_ids` — whether any ground-truth session was represented in retrieval

This gives the same extraction→retrieval→justification pipeline diagnostic as LoCoMo.

## Consolidation

Run consolidation pass after extraction for all questions. This is essential for
knowledge-update questions where Pallium's FactConsolidationStrategy detects contradictions.
Same pattern as MABench:

Follow MABench's exact pattern including the exception guard and conditional re-reconcile:

```python
consolidation_count = 0
for use_case in ("conversational_knowledge", "agent_conversation_memory"):
    while True:
        try:
            result = service.run_consolidation_pass(use_case=use_case)
        except (ValueError, KeyError):
            break
        if result is None:
            break
        consolidation_count += 1
if consolidation_count:
    service.reconcile_vector_index()  # index new fact_summary objects
```

The `try/except` handles packages not present in the config. The second
`reconcile_vector_index()` is conditional — only needed when consolidation
created new objects.

Add `--skip-consolidation` flag for comparison runs.

## DB caching

Per-question caching (same pattern as LoCoMo but keyed on question_id):
- Cache dir: `evals/longmemeval/db_cache/`
- Files: `{question_id}.db` + `{question_id}.vector.index*`
- On cache hit: copy to temp dir, skip ingestion+extraction+consolidation
- On cache miss: full pipeline, then copy to cache
- `--rebuild-db-cache` forces reprocessing

## CLI

```
python -m evals.longmemeval_benchmark --download [--variant s|oracle]
python -m evals.longmemeval_benchmark --mini
python -m evals.longmemeval_benchmark --limit-questions 10
python -m evals.longmemeval_benchmark --question-types knowledge-update temporal-reasoning
python -m evals.longmemeval_benchmark --cache-dir .local/llm-cache
python -m evals.longmemeval_benchmark --skip-consolidation
```

Arguments:
- `--dataset` — path to JSON file (default: `evals/longmemeval/datasets/longmemeval_s_cleaned.json`)
- `--output-dir` — output root (default: `evals/longmemeval/output`)
- `--download` — fetch dataset from HuggingFace
- `--variant` — which variant to download: `s` (default) or `oracle`
- `--limit-questions` — cap total questions
- `--question-types` — filter to specific categories (nargs=*)
- `--query-limit` — results per query (default: 10)
- `--cache-dir` — LLM extraction cache directory
- `--db-cache-dir` — cache processed DBs (default: `evals/longmemeval/db_cache`)
- `--rebuild-db-cache` — force reprocessing
- `--mini` — 3 questions per category for fast iteration (18 questions)
- `--verbose-results` — full retrieval details in JSONL
- `--run-name` — custom run ID
- `--skip-consolidation` — skip consolidation pass

## Output structure

```
evals/longmemeval/output/{run_id}/
  results.jsonl    — one JSON line per question
  summary.json     — aggregated metrics
  report.md        — human-readable report
```

## Per-result JSONL fields

```python
{
    "question_id": str,
    "question": str,
    "question_type": str,
    "question_date": str,
    "gold_answer": str,
    "predicted_answer": str,
    "answer_reasoning": str,
    "correct": bool,
    "judge_reasoning": str,
    "is_abstention": bool,
    "result_count": int,
    "should_inject": bool,
    "decision_reason": str,
    "injectable_block_count": int,
    "retrieval_summary": {...},
    "gold_in_context": bool,
    "evidence_trace": {
        "has_answer_source_ids": [...],
        "extraction_found": bool,
        "retrieval_found": bool,
        "answer_session_hit": bool,
    },
}
```

## Report sections

1. Overall accuracy
2. Per-category accuracy table (all 6 types + abstention)
3. Per-category gold_in_context rate, injection rate, answer_session_hit rate
4. Pipeline diagnostic (extraction → retrieval → context → correct)
5. Loss breakdown by stage
6. Sample failures (up to 10)

## Implementation plan

1. Create `evals/longmemeval_benchmark.py` with:
   - `main()` — CLI entry point
   - `run_longmemeval_benchmark()` — public entry point
   - `_download_dataset()` — HuggingFace direct file download
   - `_evaluate_question()` — per-question: ingest → extract → consolidate → query → answer → judge
   - `_ingest_sessions()` — map LongMemEval sessions to POST /items
   - `_parse_longmemeval_date()` — parse "2023/04/10 (Mon) 17:50" format
   - `_generate_answer()` — answer from retrieved context (includes question_date)
   - `_judge_answer()` — type-specific LLM judge
   - `_build_evidence_trace()` — trace has_answer turns through pipeline
   - `_format_retrieved_context()` — reuse LoCoMo's pattern
   - `_build_summary()` — aggregate metrics
   - `_build_report()` — markdown report
   - Utility helpers: `_copy_vector_index`, `_build_run_id`, etc.

2. No other files modified. This runner is standalone and does not integrate with
   `benchmark_architecture.py`'s `build_suite_summary` — it produces its own report.
   A `"longmemeval"` suite config entry can be added later if dashboard integration is needed.

## Verification

- `python -m evals.longmemeval_benchmark --download` succeeds
- `python -m evals.longmemeval_benchmark --download --variant oracle` succeeds
- `python -m evals.longmemeval_benchmark --mini --dataset evals/longmemeval/datasets/longmemeval_oracle.json` produces a report
- Output files exist and have correct structure
