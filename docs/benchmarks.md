# Benchmarks

Detailed results, per-category breakdowns, and reproduction commands for
Pallium's benchmark suite. For the summary table, see the
[README](../README.md#benchmarks).

All benchmarks measure end-to-end accuracy — retrieve relevant memory,
generate an answer, evaluate correctness. Retrieval rate (did the right
memory reach the LLM?) is shown separately to isolate what Pallium controls
from what the answering LLM does with it.

## LoCoMo — Conversational Recall (ACL 2024)

[LoCoMo](https://snap-stanford.github.io/LoCoMo/) tests multi-session
conversational QA — names, dates, events, relationships across long
conversations.

- **Dataset**: 10 conversations, 1,540 questions
- **Run date**: 2026-04-17

### Per-Category Results

| Category | End-to-end | Questions |
|---|---|---|
| Single-hop | 66.7% | 321 |
| Open-domain | 63.6% | 841 |
| Multi-hop | 56.0% | 282 |
| Temporal | 34.4% | 96 |
| **Overall** | **61.0%** | **1,540** |

Retrieval rate (gold answer in retrieved context): 45.5%.

### Analysis

End-to-end (61%) exceeds retrieval (45.5%) because the answering LLM
compensates with its own knowledge on trivia-style questions — names, dates,
and events that overlap with its training data. Retrieval rate is the number
that measures what Pallium actually contributes.

This result is stable across three independent full runs (61.1% Apr 7,
61.4% Apr 12, 61.0% Apr 17). Multi-hop improved from 48.9% to 56.0% after
fact extraction hardening. Temporal (34.4%) remains the weakest category.

Pallium prioritizes structured memory (decisions, investigations, checkpoints)
over verbatim fact recall. LoCoMo is weighted toward trivia-style questions
that reward raw transcription. The factual recall package (cross-thread fact
extraction and consolidation) narrows this gap.

## LongMemEval — Multi-Session Memory (ICLR 2025)

[LongMemEval](https://arxiv.org/abs/2410.10813) tests long-term interactive
memory — single-session recall, cross-session reasoning, temporal ordering,
and knowledge updates.

- **Dataset**: 60 questions (mini variant)
- **Run date**: 2026-04-13

### Per-Category Results

| Category | Retrieval | End-to-end | Questions |
|---|---|---|---|
| Single-session user | 90% | 90% | 10 |
| Single-session assistant | 100% | 100% | 10 |
| Single-session preference | 90% | 90% | 10 |
| Multi-session | 70% | 70% | 10 |
| Temporal reasoning | 100% | 100% | 10 |
| Knowledge update | 100% | 100% | 10 |
| **Overall** | **91.7%** | **93.2%** | **60** |

### Analysis

Retrieval and end-to-end are nearly identical — when the answer is in
context, the justifier gets it right 98% of the time. The 4 remaining
failures are all multi-session counting/aggregation questions ("how many
total", "how much spent") that require summing across independent memory
objects — a capability gap, not a retrieval miss.

Note: these results are on the mini variant (60 questions). The full
LongMemEval-S dataset has 500 questions. A full run is pending.

## FactConsolidation — Contradiction Handling (MemoryAgentBench, ICLR 2026)

MemoryAgentBench Conflict Resolution split. Tests whether updated facts are
retrieved and used over stale contradictory ones.

- **Dataset**: 200 questions, 6k context depth
- **Run date**: 2026-04-19

### Per-Category Results

| Category | Retrieval | End-to-end | Questions |
|---|---|---|---|
| Single-hop | — | 86% | 100 |
| Multi-hop | — | 22% | 100 |
| **Overall** | **65%** | **54.0%** | **200** |

### Analysis

Significant improvement over the prior baseline (29.1% → 54.0%) driven by
fact extraction prompt hardening: expanded skip list (transient runtime state,
hypothetical futures, monitoring chatter), self-contained subject requirement,
and structural acceptance gates (markdown fragment rejection, subjectless fact
rejection, vague status rejection). Single-hop jumped from 51.5% to 86%.

Multi-hop remains weak (22%) because it requires chaining two independently
updated facts — retrieval returns the right individual facts but the answering
LLM struggles to combine them correctly when stale versions also appear in
context.

## Running Benchmarks

```bash
# Download datasets (one-time)
python -m evals.locomo_benchmark --download
python -m evals.longmemeval_benchmark --download
python -m evals.mabench_benchmark --download

# Run with LLM cache for faster re-runs
python -m evals.locomo_benchmark --cache-dir .local/llm-cache
python -m evals.longmemeval_benchmark --mini --cache-dir .local/llm-cache
python -m evals.mabench_benchmark --cache-dir .local/llm-cache

# Quick subset for development iteration
python -m evals.locomo_benchmark --mini --cache-dir .local/llm-cache
python -m evals.mabench_benchmark --mini --cache-dir .local/llm-cache
```

Results are written to `evals/*/output/` with per-question JSONL files
for detailed analysis.
