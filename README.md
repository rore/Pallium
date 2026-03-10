![Pallium Banner](assets/logo/pallium_header.png)

# Pallium

Pallium is a generic memory engine for agents.

It stores selected source items, derives reusable knowledge through extensible semantic layers, and returns compact evidence-backed memory objects to consumers.

The current product focus is the first semantic package, `agent_conversation_memory`. That narrows the first value claim, not the scope of the Pallium platform itself.

## What Exists Now

Current implemented shape:

- one local-first FastAPI service
- one generic core
- semantic plugins with deterministic and LLM-backed paths
- an explicit `agent_conversation_memory` runtime package over the LLM-backed semantic path
- provider abstraction for OpenAI-compatible and Claude-style APIs
- SQLite-backed storage behind a storage boundary
- mixed retrieval over memory hits and compact source hits
- explicit event refs for message and assistant-artifact ingest
- first concrete product package: agent conversation memory over user messages and final assistant outputs
- typed memory for:
  - `decision`
  - `investigation_outcome`
  - fallback `discussion_summary`
- minimal memory lifecycle with `active` and `superseded`
- committed semantic regression set and eval harness
- realistic agent-conversation scenario test bed and runner
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
- memory objects are evidence-backed through explicit relations
- retrieval returns compact cards rather than raw source payloads by default
- superseded memory is filtered from default retrieval, while raw evidence remains intact

## Semantic Direction

Current semantic package focus:

- `agent_conversation_memory` as the first explicit product package
- MVP evidence model:
  - `artifact_kind="message"` with `role="user"`
  - `artifact_kind="assistant_output"` with `role="assistant"`
- target value questions:
  - what did we already conclude?
  - why did we choose this?
  - have we answered this before?
  - what prior agent-conversation context should carry into this new thread?
- out of scope for this package:
  - ambient workplace chat that never flowed through an agent
  - full transcript replay as the default retrieval goal

Current semantic output supports:

- `decision`
- `investigation_outcome`
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

Pallium now includes a committed semantic regression batch at [C:/Dev/rore/Pallium/evals/semantic/input/items.jsonl](C:/Dev/rore/Pallium/evals/semantic/input/items.jsonl).

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

Pallium now also includes a realistic agent-conversation scenario harness built around a neutral public-safe sample domain: library reservation and catalog sync.

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

This harness is the realistic proof layer for the `agent_conversation_memory` package and the input to the later recurring-question value benchmark.

## Recurring-Question Value Benchmark

Pallium now also includes a user-facing recurring-question benchmark that compares final downstream answers between:

- baseline current-thread context only
- current-thread context plus Pallium memory-backed retrieval

Run it with:

```powershell
.\.venv\Scripts\python.exe -m evals.recurring_question_benchmark
```

Each run writes:

- `summary.json`
- `results.jsonl`

The committed benchmark is the first user-facing proof layer for whether Pallium improves recurring-question handling before higher-level memory is added.
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

