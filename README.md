# Pallium

Pallium is a generic memory engine for agents.

It stores selected source items, derives reusable knowledge through extensible semantic layers, and returns compact evidence-backed memory objects to consumers.

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

Create [C:/Dev/rore/Pallium/.env.local](C:/Dev/rore/Pallium/.env.local) from [C:/Dev/rore/Pallium/.env.example](C:/Dev/rore/Pallium/.env.example).

Example OpenAI-compatible setup:

```env
PALLIUM_DEFAULT_USE_CASE=agent_conversation_memory
PALLIUM_LLM_PROVIDER=openai_compatible
PALLIUM_LLM_MODEL=gpt-5-mini
PALLIUM_LLM_BASE_URL=https://api.openai.com/v1
PALLIUM_LLM_API_KEY=your-key
PALLIUM_LLM_PROMPT_VARIANT=strict_typed_memory_v4_evidence_guarded
```

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
