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
- **Run date**: 2026-04-12

### Per-Category Results

| Category | Retrieval | End-to-end | Questions |
|---|---|---|---|
| Single-hop | 55.1% | 71.7% | — |
| Open-domain | 54.5% | 63.9% | — |
| Temporal | 38.5% | 41.7% | — |
| Multi-hop | 40.8% | 48.9% | — |
| **Overall** | **51.1%** | **62.0%** | **1,540** |

### Analysis

End-to-end (62%) exceeds retrieval (51.1%) because the answering LLM
compensates with its own knowledge on trivia-style questions — names, dates,
and events that overlap with its training data. About 11% of correct answers
come from the LLM, not from Pallium's retrieval. Retrieval rate is the number
that measures what Pallium actually contributes.

Temporal (38.5% retrieval) and multi-hop (40.8% retrieval) are the weakest
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

- **Dataset**: 200 questions, 6k context depth (455 facts)
- **Run date**: 2026-04-12

### Per-Category Results

| Category | Retrieval | End-to-end | Questions |
|---|---|---|---|
| Single-hop | 82% | 51.5% | 100 |
| Multi-hop | 10% | 7% | 100 |
| **Overall** | **64.5%** | **29.1%** | **200** |

### Analysis

The retrieval-to-accuracy gap on single-hop is the main open problem: the
updated fact reaches the context (82%) but older memory objects that haven't
been superseded outnumber the newer fact, causing the answering LLM to pick
the stale value (51.5% correct). This is the contradiction supersession
problem — thread summaries and discussion summaries containing old facts
persist alongside the corrected atomic fact.

Multi-hop retrieval is very low (10%) because it requires chaining two
independent facts that were updated separately — not yet supported.

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
