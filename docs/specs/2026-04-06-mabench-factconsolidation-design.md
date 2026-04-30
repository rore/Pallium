# MABench FactConsolidation Benchmark

## Purpose

Add FactConsolidation (from MemoryAgentBench) as an external benchmark for contradiction handling. This is the only publicly available benchmark that tests whether a memory system prefers newer contradictory information over stale facts — a capability Pallium needs but does not yet fully implement.

The benchmark establishes a diagnostic baseline. Low initial numbers are expected and useful — they quantify specific gaps (cross-thread supersession, extraction coverage, recency ranking) that drive future work.

## Dataset

**Source:** MemoryAgentBench (ICLR 2026), HuggingFace `ai-hyz/MemoryAgentBench`, `Conflict_Resolution` split.
**License:** MIT (code), CC BY 4.0 (data).
**Paper:** arXiv 2507.05257.

Two datasets:

| ID | Dataset | Rows | Questions | Context Depth | Metric |
|---|---|---|---|---|---|
| `sf-sh` | FactConsolidation-SH | ~4 | ~100 | 6K / 32K / 64K / 262K variants | SubEM |
| `sf-mh` | FactConsolidation-MH | ~4 | ~100 | 6K / 32K / 64K / 262K variants | SubEM |

**How FactConsolidation works:** Each test case embeds original facts and contradictory rewrites in a long text of padding. Rewrites appear later with higher serial numbers, establishing them as "newer." Questions ask about the updated facts. The expected answer is the newer version.

- **Single-hop (SF-SH):** One fact update, one question. "What is the capital of Brazil?" → "Rio de Janeiro" (the rewrite), not "Brasilia" (the original).
- **Multi-hop (SF-MH):** Chained updates requiring inference. "What is the official language of the country whose capital was recently changed to Rio de Janeiro?" — requires combining the updated fact with other knowledge.

**Comparison baselines (from the paper):**

| Agent | SF-SH 262K | SF-MH 262K |
|---|---|---|
| GPT-4o (long-context) | 60% | 5% |
| Claude 3.7 Sonnet (long-context) | 45% | 0% |
| Mem0 | 20% | 0% |
| Zep | 10% | 0% |
| BM25 RAG | 45% | 6% |

SF-MH at scale is essentially unsolved. Even o4-mini drops from 80% (6K context) to 14% (32K).

## File Structure

```
evals/
  mabench_benchmark.py          # Runner (single file, like locomo_benchmark.py)
  mabench/
    datasets/                    # Downloaded + cached dataset files
    db_cache/                    # Cached processed DBs per test row
    output/                      # Run results (summary.json, results.jsonl, report.md)
```

## CLI Interface

```bash
# Download dataset (first time)
python -m evals.mabench_benchmark --download

# Run both SF datasets (default)
python -m evals.mabench_benchmark

# Run specific variant
python -m evals.mabench_benchmark --datasets sf-sh
python -m evals.mabench_benchmark --datasets sf-mh

# Context depth variant (6k, 32k, 64k, 262k — default: 262k)
python -m evals.mabench_benchmark --context-depth 32k

# With caching
python -m evals.mabench_benchmark --db-cache-dir evals/mabench/db_cache --cache-dir .local/llm-cache

# Mini mode (subset of questions)
python -m evals.mabench_benchmark --mini
```

## Data Download

Two mechanisms:

1. **Primary:** `--download` flag uses urllib to fetch the Parquet file from HuggingFace, extracts the `Conflict_Resolution` split, converts to local JSON in `evals/mabench/datasets/`. No dependency on the `datasets` library.

2. **Fallback:** If `datasets` library is installed, can use `load_dataset("ai-hyz/MemoryAgentBench", split="Conflict_Resolution")` directly.

The downloaded data is cached locally. Subsequent runs read from the local JSON cache.

## Adaptation for Pallium

FactConsolidation data is chunked document text, not conversation. Three adaptations make it compatible with Pallium's pipeline:

### Chunking into Threads

Split context into thread groups of ~10-15 chunks. Each group becomes a separate thread within one container.

- `container_ref` = `mabench-{dataset}-row{N}` (one container per test row)
- `thread_ref` = `mabench-{dataset}-row{N}-t{M}` (one thread per chunk group)
- Chunk size: 4096 tokens, sentence-aligned (matching MABench's chunking)

This keeps each thread within Pallium's practical extraction range. The thread-level fact extraction window is 6000 chars — with 10-15 chunks of ~16K chars each, significant truncation occurs. This is expected and the benchmark quantifies its impact.

### Synthetic Timestamps

Assign monotonically increasing `occurred_at` timestamps based on chunk position:

- Chunk 0 → `2024-01-01T00:00:00Z`
- Chunk 1 → `2024-01-01T01:00:00Z`
- ... (1-hour increments)

This gives Pallium's temporal sorting the signal needed for recency-based ranking.

### Source Item Mapping

Each chunk → one source item:

- `source_type` = `chat_message`
- `role` = `user`
- `artifact_kind` = `message`
- `content` = chunk text
- `occurred_at` = synthetic timestamp
- `visibility` = `public`

This matches the `ELIGIBLE_ARTIFACT_ROLES` in `conversational_knowledge.py` so both semantic packages process the items.

## Evaluation Pipeline

Per test row:

1. **Ingest** — chunk context, assign to threads + timestamps, POST /items in batches of 50
2. **Extract** — `drain_processing_queue()` + `reconcile_vector_index()`
3. **Query** — each question via POST /query/debug with `query_limit=10`
4. **Score** — layered metrics (see below)

Uses TestClient + temp SQLite DB per test row, same pattern as LoCoMo.

## Metrics

### Primary: SubEM Accuracy

Comparable to MABench published baselines.

- Generate answer from retrieved context using LLM justifier (same pattern as LoCoMo)
- Score: `gold_answer.lower() in predicted_answer.lower()`

### Diagnostic: Layered Pipeline Breakdown

For each question, trace where the answer was lost:

1. **Source retrieval** — Did the chunk containing the newer fact appear as a `source_hit` in retrieval results?
2. **Fact extraction** — Was the newer fact extracted as an `atomic_fact` memory object?
3. **Supersession** — Was the older fact's memory object (if any) superseded (lifecycle = "superseded")?
4. **Ranking** — When both old and new facts appear in results, does the newer one rank higher?
5. **End-to-end** — Did the LLM justifier produce the correct (newer) answer?

### Identifying Old vs. New Facts

FactConsolidation metadata includes which facts are original and which are rewrites, plus the entity/relation being modified. The benchmark uses this to:

- Build a lookup of original-fact text snippets and rewrite-fact text snippets per question
- After retrieval, scan results (both memory_hits and source_hits) for substring matches against both versions
- Classify each question into: `newer_preferred`, `older_preferred`, `both_found_newer_higher`, `both_found_older_higher`, `only_newer`, `only_older`, `neither_found`

## Known Limitations (Expected Baseline Gaps)

These are not design flaws — they are the gaps the benchmark is designed to surface and track:

1. **No cross-thread supersession.** Pallium's supersession is thread-scoped via canonical_key. Original and rewrite facts in different threads both survive as active memory. This is the primary capability gap.

2. **Fact extraction truncation.** The conversational_knowledge package extracts facts per-thread with a 6000-char window. With 10-15 chunks of ~16K chars per thread, most content is truncated. Facts outside the window are missed at the extraction level (but may still be found via source_hit retrieval).

3. **Per-item extraction mismatch.** The agent_conversation_memory per-item extraction sees full chunks but looks for decisions/investigations/interests — not atomic facts in document text. Most chunks produce turn_summary or nothing.

4. **Multi-hop reasoning.** SF-MH requires chaining multiple updated facts. Even if individual facts are retrieved correctly, the LLM justifier must combine them — a generation-layer capability beyond Pallium's scope.

## Output Format

Same structure as LoCoMo:

- `results.jsonl` — per-question: question, gold answer, predicted answer, correct (SubEM), pipeline layer classification, retrieval summary
- `summary.json` — aggregated: overall SubEM accuracy, per-dataset breakdown, pipeline diagnostic rates, recency classification distribution
- `report.md` — human-readable report

### Report Structure

```
# MABench FactConsolidation Report

Run ID: `mabench-sf__provider__model__timestamp`
Context depth: 262k

## Overall Accuracy
**X%** (Y/Z correct)

## By Dataset
| Dataset | Correct | Total | Accuracy |
|---------|---------|-------|----------|
| sf-sh   | ...     | ...   | ...%     |
| sf-mh   | ...     | ...   | ...%     |

## Pipeline Diagnostic
- Source retrieval (newer fact in source_hits): X%
- Fact extraction (newer fact as atomic_fact): X%
- Supersession (older fact superseded): X%
- Ranking (newer > older when both present): X%
- End-to-end (correct answer): X%

## Recency Classification
- newer_preferred: X%
- older_preferred: X%
- both_found_newer_higher: X%
- both_found_older_higher: X%
- only_newer: X%
- only_older: X%
- neither_found: X%
```

## Cost Estimate

At 262K context depth with 4096-token chunks: ~64 chunks per test row. With 8 rows total:

- **Extraction LLM calls:** ~512 per-item calls (agent_conversation_memory) + ~40-50 thread-level calls (conversational_knowledge). With LLM cache, only first run pays this cost.
- **Justifier LLM calls:** ~200 questions × 1 call each = ~200 calls per run. Not cached (different retrieved context each time).
- **No LLM judge calls.** SubEM is offline string matching.

At 32K context depth: ~8 chunks per row, ~64 extraction calls total. Good for fast iteration.

## Implementation Notes

- Follow LoCoMo patterns exactly: TestClient, temp DB, DB caching, LLM caching, ThreadPoolExecutor for parallel justifier calls
- Reuse `_wrap_providers_with_cache` from the invariant runner for LLM caching
- The `--context-depth` flag selects which rows to use — MABench provides the same questions at different context depths as separate rows in the dataset
- The `--mini` flag limits to N questions per dataset for quick iteration
- Dataset files are gitignored (downloaded on demand, not checked in)
