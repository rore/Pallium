![Pallium Banner](assets/logo/pallium_header.png)

# Pallium

Pallium is a generic memory engine for agents.

It stores selected source items, derives reusable knowledge through extensible semantic layers, and returns compact evidence-backed memory objects to consumers.

The current product focus is the first semantic package, `agent_conversation_memory`. That narrows the first value claim, not the scope of the Pallium platform itself.

## What Exists Now

Current implemented shape:

- one local-first FastAPI service
- one generic core
- one reusable capability layer with thread aggregation and bounded consolidation
- semantic plugins with deterministic and LLM-backed paths
- an explicit `agent_conversation_memory` runtime package over the LLM-backed semantic path
- provider abstraction for OpenAI-compatible and Claude-style APIs with conservative retries, backoff, request-id capture, and bounded concurrency
- SQLite-backed storage behind a storage boundary
- mixed retrieval over memory hits and compact source hits
- package-owned internal routing over higher-level memory, lower-level memory, and source evidence
- explicit event refs for message and assistant-artifact ingest
- first concrete product package: agent conversation memory over user messages, final assistant outputs, and selected assistant-originated work artifacts for bounded progress, blocker, and next-step continuity
- typed and higher-level memory for:
  - `decision`
  - `investigation_outcome`
  - `thread_summary`
  - `pattern_memory`
  - `continuity_memory`
  - `task_checkpoint`
  - fallback `discussion_summary`
- minimal memory lifecycle with `active` and `superseded`
- committed semantic regression set and eval harness
- realistic agent-conversation scenario test bed and runner
- recurring-question value benchmark
- work-resumption continuity benchmark
- memory-routing benchmark for routed retrieval policy
- simulation script, Bruno collection, and pytest coverage

## Core Concepts

The core centers on five generic primitives:

- `SourceItem`
- `Annotation`
- `Relation`
- `IndexEntry`
- `MemoryObject`

Important current behavior:

- source items are the evidence layer
- semantic plugins promote reusable memory from source items
- thread aggregation now exists as a reusable capability above atomic source items
- bounded consolidation now exists as a reusable capability above lower-level memory
- memory objects are evidence-backed through explicit relations
- retrieval returns compact cards rather than raw source payloads by default
- the current package can internally rerank retrieved candidates by question shape without changing the public `/query` contract
- superseded memory is filtered from default retrieval, while raw evidence remains intact

## Semantic Direction

Current semantic package focus:

- `agent_conversation_memory` as the first explicit product package
- current bounded evidence model:
  - `artifact_kind="message"` with `role="user"`
  - `artifact_kind="assistant_output"` with `role="assistant"`
  - selected assistant-originated work artifacts:
    - `artifact_kind="tool_use_summary"` with `role="assistant"` for explicit progress or blocker state
    - `artifact_kind="todo_snapshot"` with `role="assistant"` for explicit next-step state
- target value questions:
  - what did we already conclude?
  - why did we choose this?
  - have we answered this before?
  - what prior agent-conversation context should carry into this new thread?
- out of scope for this package:
  - ambient workplace chat that never flowed through an agent
  - raw tool logs, raw MCP events, or exhaustive runtime-notification ingest
  - full transcript replay as the default retrieval goal

Current semantic output supports:

- `decision`
- `investigation_outcome`
- `thread_summary`
- `task_checkpoint`
- `pattern_memory`
- `continuity_memory`
- `discussion_summary`

The LLM-backed path records semantic provenance with each derived artifact:

- prompt schema id
- prompt schema version
- prompt variant

Default LLM prompt path:

- prompt variant: `strict_typed_memory_v4_evidence_guarded`
- prompt schema: `typed_memory_extraction`
- prompt schema version: `v4`

## Semantic Regression

Pallium includes a committed semantic regression batch at [C:/Dev/rore/Pallium/evals/semantic/input/items.jsonl](C:/Dev/rore/Pallium/evals/semantic/input/items.jsonl).

Latest recorded baseline:

- provider: OpenAI-compatible
- model: `gpt-5-mini`
- prompt variant: `strict_typed_memory_v4_evidence_guarded`
- overall correct: `30 / 30`
- decision false positives: `0`
- investigation false positives: `0`
- false negatives: `0`

See [C:/Dev/rore/Pallium/evals/semantic/baseline.md](C:/Dev/rore/Pallium/evals/semantic/baseline.md).

## Agent Conversation Test Bed

Pallium includes a realistic agent-conversation scenario harness built around a neutral public-safe sample domain: library reservation and catalog sync.

Run it with:

```powershell
.\.venv\Scripts\python.exe -m evals.agent_conversation_runner
```

Each run writes:

- `summary.json`
- `results.jsonl`

The scenarios compare:

- baseline current-thread context only
- current-thread context plus Pallium memory-backed retrieval

Thread-level summaries now sit between atomic events and higher-level memory, and bounded consolidation can now produce evidence-backed higher-level memory over `thread_summary`, `decision`, and `investigation_outcome`: `pattern_memory` for broad recurring recall, `continuity_memory` for repeated-answer carry-forward, and `task_checkpoint` for resumed-work continuity when selected work artifacts support it.

## Recurring-Question Value Benchmark

Pallium also includes a user-facing recurring-question benchmark that compares final downstream answers between:

- baseline current-thread context only
- current-thread context plus Pallium memory-backed retrieval

Run it with:

```powershell
.\.venv\Scripts\python.exe -m evals.recurring_question_benchmark
```

Each run writes:

- `summary.json`
- `results.jsonl`

The committed benchmark is the first user-facing proof layer for whether Pallium improves recurring-question handling with current-thread context, lower-level memory, and later higher-level memory modes.

The current package now also uses internal routed retrieval policy so broad recall, repeated-answer continuity, resumed-work continuation, precise factual lookup, and evidence-trace questions can prefer different layers while remaining inspectable through `/query/debug`.

## Work Resumption Benchmark

Pallium now includes a bounded work-resumption benchmark for workflow continuity within the current `agent_conversation_memory` slice.

It measures whether retrieved memory and source evidence help an agent stay oriented across:

- resumed investigation after a pause
- debugging continued from partial findings
- resumed work after auth or tool failure with partial progress preserved
- resumed implementation or ticket work after interruption
- no-value continuation cases where the current thread should already be enough

The benchmark scores:

- task orientation
- prior findings reuse
- blocker state carry-forward
- preserved progress
- next-step guidance

The gap rollup is hypothesis-driven: scenario-authored `dimension_gap_targets` contribute to it, so the benchmark should be treated as a directional guide to the next continuity slice rather than a neutral discovery engine.

It reports authored continuity-gap signals that can indicate the next hardening slice, such as:

- routing or layer choice
- result packaging or evidence
- retrieval recall

That benchmark guidance first led to bounded selected work-artifact support, and it now also exercises compact `task_checkpoint` memory for resumed-work continuity without broadening into runtime-log ingest.

Run it with:

```powershell
.\.venv\Scripts\python.exe -m evals.work_resumption_benchmark
```

Each run writes:

- `summary.json`
- `results.jsonl`
- `report.md`

## Memory Routing Benchmark

Pallium now includes a dedicated benchmark for the current routed retrieval policy over broad recall, repeated-answer continuity, precise fact lookup, evidence-trace questions, and non-value guard cases.

Run it with:

```powershell
.\.venv\Scripts\python.exe -m evals.memory_routing_benchmark
```

Each run writes:

- `summary.json`
- `results.jsonl`
- `report.md`

The current deterministic stub benchmark is intended to validate the routed policy end to end across broad recall, continuity, precise fact, evidence-trace, paraphrase, and guard scenarios before later retrieval expansion.

## Tiered Memory and Strategy Comparison

Pallium now includes the first bounded tiered-memory capability.

It can build bounded higher-level memory over:

- `thread_summary`
- `decision`
- `investigation_outcome`

Current higher-level kinds:

- `pattern_memory` for broad recurring cross-thread recall
- `continuity_memory` for repeated-answer continuity and compact carry-forward
- `task_checkpoint` for compact resumed-work state, blockers, next steps, and evidence

Three bounded selection/grouping strategies are implemented and comparable:

- `thread_local_carry_forward`
- `container_topic_window`
- `thread_summary_anchored`

Current package default:

- `thread_summary_anchored`

Why this default:

- keeps thread summaries as the main interpretable unit
- allows bounded cross-thread carry-forward
- stayed conservative on the current false-merge guard scenario

Run the comparison harness with:

```powershell
.\.venv\Scripts\python.exe -m evals.consolidation_strategy_runner
```

Each run writes:

- `summary.json`
- `results.jsonl`


## Public Corpus Benchmark

Pallium now includes a bounded public-corpus eval path for messy real user-assistant interactions without depending on private downstream traffic.

Current public-corpus layer:

- WildChat remains the primary realism corpus
- WildBench is the complementary task-oriented benchmark source
- raw corpora stay outside the repo
- reviewed manifests define the committed benchmark slices
- local helpers keep the full-corpus workflows reproducible without changing the public benchmark contract
- the benchmark reports whether misses look like retrieval recall, routed layer choice, result packaging/evidence, or overreach

Recommended local WildChat layout:

- `C:\data\wildchat\WildChat-4.8M\snapshot`: downloaded Hugging Face dataset snapshot
- `C:\data\wildchat\WildChat-4.8M\derived\conversation_index.sqlite`: local candidate index for slice review
- `C:\data\wildchat\WildChat-4.8M\derived\review_candidates.jsonl`: candidate episodes for human review
- `C:\data\wildchat\WildChat-4.8M\derived\review_sets\wildchat_review_manifest\conversations.json`: small materialized corpus for the committed reviewed slice
- `C:\data\wildchat\WildChat-4.8M\runs\...`: repeated benchmark outputs

WildChat setup:

```powershell
.\.venv\Scripts\python.exe -m pip install huggingface_hub pyarrow
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local download --root C:\data\wildchat\WildChat-4.8M
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local validate --root C:\data\wildchat\WildChat-4.8M
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local build-candidate-index --root C:\data\wildchat\WildChat-4.8M
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local emit-candidates --root C:\data\wildchat\WildChat-4.8M
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local materialize-review-set --root C:\data\wildchat\WildChat-4.8M --reviewed-manifest evals\public_corpus\wildchat_review_manifest.json
.\.venv\Scripts\python.exe -m evals.public_corpus_wildchat_local benchmark --root C:\data\wildchat\WildChat-4.8M --reviewed-manifest evals\public_corpus\wildchat_review_manifest.json --run-name local-public-corpus-benchmark
```

Recommended local WildBench layout:

- `C:\data\wildbench\WildBench\snapshot`: downloaded Hugging Face dataset snapshot
- `C:\data\wildbench\WildBench\derived\review_candidates.jsonl`: candidate episodes for human review
- `C:\data\wildbench\WildBench\derived\review_sets\wildbench_review_manifest\conversations.json`: small materialized corpus for the committed reviewed slice
- `C:\data\wildbench\WildBench\runs\...`: repeated benchmark outputs

WildBench setup:

```powershell
.\.venv\Scripts\python.exe -m pip install huggingface_hub pyarrow
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local download --root C:\data\wildbench\WildBench
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local validate --root C:\data\wildbench\WildBench
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local emit-candidates --root C:\data\wildbench\WildBench
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local materialize-review-set --root C:\data\wildbench\WildBench --reviewed-manifest evals\public_corpus\wildbench_review_manifest.json
.\.venv\Scripts\python.exe -m evals.public_corpus_wildbench_local benchmark --root C:\data\wildbench\WildBench --reviewed-manifest evals\public_corpus\wildbench_review_manifest.json --run-name local-public-corpus-wildbench-benchmark
```

The committed repo assets live under [C:/Dev/rore/Pallium/evals/public_corpus](C:/Dev/rore/Pallium/evals/public_corpus).
## Tiered-Memory Validation Benchmark

Pallium includes a dedicated benchmark for deciding when higher-level `pattern_memory` is actually useful and which consolidation strategy is safest.

Run it with:

```powershell
.\.venv\Scripts\python.exe -m evals.tiered_memory_validation_runner
```

Each run writes:

- `summary.json`
- `results.jsonl`

The benchmark compares:

- baseline current-thread context only
- lower-level memory without tiered consolidation
- tiered memory with:
  - `thread_local_carry_forward`
  - `container_topic_window`
  - `thread_summary_anchored`

Current recorded direction:

- `container_topic_window` is strongest for broad cross-thread prior-conclusion questions and tends to produce `pattern_memory`
- `thread_local_carry_forward` and bounded single-thread `thread_summary_anchored` are better for repeated-answer continuity and can produce `continuity_memory`
- precise factual and evidence-heavy questions should still prefer lower-level memory over higher-level memory
- all current strategies stayed false-merge-safe on the committed validation scenarios

## Run Locally

From the repo root:

```powershell
& "C:\Users\I347041\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
.\.venv\Scripts\python.exe examples\agent_memory_simulation.py
```

## Local Config

Use a structured local config file for package and provider setup:

- copy [C:/Dev/rore/Pallium/pallium.example.toml](C:/Dev/rore/Pallium/pallium.example.toml) to `pallium.local.toml`
- copy [C:/Dev/rore/Pallium/.env.example](C:/Dev/rore/Pallium/.env.example) to [C:/Dev/rore/Pallium/.env.local](C:/Dev/rore/Pallium/.env.local) for secrets and one-off overrides

Recommended split:

- `pallium.local.toml`
  - default package
  - storage backend
  - named LLM providers
  - package-specific model and prompt configuration
- `.env.local`
  - API keys
  - temporary overrides

Example `pallium.local.toml`:

```toml
default_use_case = "agent_conversation_memory"

[storage]
backend = "sqlite"
sqlite_url = "sqlite:///./pallium.db"

[llm_providers.openai]
kind = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key_env = "PALLIUM_OPENAI_API_KEY"
timeout_seconds = 30
max_attempts = 3
base_backoff_ms = 250
max_backoff_ms = 3000
jitter_ratio = 0.2
max_concurrency = 4

[semantic_packages.agent_conversation_memory]
implementation = "agent_conversation_memory"
llm_provider = "openai"
model = "gpt-5-mini"
prompt_variant = "strict_typed_memory_v4_evidence_guarded"
```

Example `.env.local`:

```env
PALLIUM_OPENAI_API_KEY=your-key
```

Environment variables still override both `.env.local` and `pallium.local.toml`.

Provider resilience defaults are configured per provider, not per package. Current default posture is conservative:

- retry only transient failures
- respect `Retry-After` when present
- bounded exponential backoff with jitter
- bounded in-process concurrency
- fail fast on invalid successful responses and non-retryable request/auth errors

## LLM Semantic Eval Harness

Run the committed regression batch:

```powershell
.\.venv\Scripts\python.exe -m evals.semantic_runner --suite-name semantic-regression --max-concurrency 4
```

Each run writes:

- `summary.json`
- `results.jsonl`

Use `--split-output` only when you want per-input debug files.

## Repository Guide

- [C:/Dev/rore/Pallium/docs/README.md](C:/Dev/rore/Pallium/docs/README.md)
- [C:/Dev/rore/Pallium/docs/context/architecture.md](C:/Dev/rore/Pallium/docs/context/architecture.md)
- [C:/Dev/rore/Pallium/docs/context/state.md](C:/Dev/rore/Pallium/docs/context/state.md)
- [C:/Dev/rore/Pallium/roadmap/board.md](C:/Dev/rore/Pallium/roadmap/board.md)

