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
- **Run date**: 2026-04-15

### Per-Category Results

| Category | Retrieval | End-to-end | Questions |
|---|---|---|---|
| Single-hop | 56.1% | 72.5% | — |
| Open-domain | 55.4% | 66.3% | — |
| Temporal | 39.5% | 43.2% | — |
| Multi-hop | 40.3% | 49.0% | — |
| **Overall** | **51.8%** | **63.0%** | **1,540** |

### Analysis

End-to-end (63%) exceeds retrieval (51.8%) because the answering LLM
compensates with its own knowledge on trivia-style questions — names, dates,
and events that overlap with its training data. About 11% of correct answers
come from the LLM, not from Pallium's retrieval. Retrieval rate is the number
that measures what Pallium actually contributes.

Temporal (39.5% retrieval) and multi-hop (40.3% retrieval) are the weakest
categories. Temporal questions require ordering events in time; multi-hop
requires combining facts from different sources. Both are active improvement
areas.

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
