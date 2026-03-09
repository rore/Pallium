# Pallium

Pallium is a generic memory engine for agents.

It stores selected source items, derives reusable knowledge through extensible
semantic layers, and returns compact evidence-backed memory objects to
consumers.

## What Pallium Is

Pallium is intended to be:

- a generic memory core
- extensible through semantic use-case layers
- local-first by default
- evidence-backed and replayable
- useful as an unstructured memory layer for agents

## What Pallium Is Not

Pallium is not intended to be:

- a system of record
- an agent runtime
- a connector platform as its primary identity
- a workflow engine
- a replacement for direct retrieval from source systems

## Current Direction

The current implementation is a walking skeleton with:

- one local-first service
- one generic core
- one semantic layer interface with in-repo plugin implementations
- one storage layer
- one mixed retrieval path over memory and source evidence
- explicit event refs for message and assistant-artifact ingest
- compact source-hit cards for agent consumers
- one deterministic typed-memory path for `decision`
- one LLM-backed semantic path compatible with OpenAI-compatible and Claude-style APIs
- one semantic eval harness that records raw LLM output, normalized extraction, and promoted artifacts
- one simulated generic agent consumer for end-to-end proof

The current top-level architecture is:

1. API layer
2. Generic core
3. Semantic layer
4. Provider layer
5. Storage layer
6. Retrieval layer
7. Optional background jobs

## Core Concepts

The generic core currently centers on five primitives:

- SourceItem
- Annotation
- Relation
- IndexEntry
- MemoryObject

The core owns storage and orchestration. Semantic layers define meaning.

Source items can now also carry explicit event refs such as `thread_ref`, `session_ref`, `container_ref`, `actor_ref`, `source_ref`, `role`, `artifact_kind`, and `occurred_at`.

## Tiered Memory

Tiered memory is an intended extension, not part of the current executable slice.

The idea is to periodically consolidate lower-level memory into higher-level
reusable memory objects such as topic summaries or recurring patterns, while
keeping all lower-level evidence intact.

## Status

The LLM-backed semantic milestone is implemented and verified.

What exists now:

- Python project scaffold
- FastAPI application wiring
- generic core models and orchestration service
- semantic plugin interface plus deterministic and LLM-backed plugins
- LLM provider abstraction plus OpenAI-compatible and Claude adapters
- storage abstraction plus SQLite implementation
- mixed retrieval over promoted memory and raw source evidence
- deterministic and LLM-backed promotion of `decision` memory objects, with `discussion_summary` used only when extraction itself produces a non-decision result
- semantic eval harness with input fixtures and per-run output artifacts
- simulation script, Bruno collection, and pytest coverage
- project context, designs, and roadmap docs

Verified locally:

- pytest passes
- the live HTTP flow works with the deterministic plugin
- the live HTTP flow also works with the LLM-backed plugin against a local fake OpenAI-compatible provider
- a real OpenAI-backed run also succeeded against a fresh temporary database

## Run Locally

From the repo root:

```powershell
& "C:\Users\I347041\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
.\.venv\Scripts\python.exe examples\agent_memory_simulation.py
```

## Local Config File

Pallium can now read a local config file for developer-friendly setup.

Supported behavior:

- default local file: `.env.local`
- optional override path: `PALLIUM_ENV_FILE`
- environment variables still take precedence over file values

To start quickly:

1. Copy [.env.example](C:/Dev/rore/Pallium/.env.example) to `.env.local`
2. Fill in the values you want
3. Start the API normally

Example `.env.local` for OpenAI-compatible testing:

```env
PALLIUM_DEFAULT_USE_CASE=llm_agent_memory
PALLIUM_LLM_PROVIDER=openai_compatible
PALLIUM_LLM_MODEL=gpt-4.1-mini
PALLIUM_LLM_BASE_URL=https://api.openai.com/v1
PALLIUM_LLM_API_KEY=your-key
```

For Claude-compatible endpoints, switch the provider and model, for example:

```env
PALLIUM_DEFAULT_USE_CASE=llm_agent_memory
PALLIUM_LLM_PROVIDER=anthropic_claude
PALLIUM_LLM_MODEL=claude-3-5-sonnet-latest
PALLIUM_LLM_BASE_URL=https://api.anthropic.com/v1
PALLIUM_LLM_API_KEY=your-key
```

## LLM Semantic Eval Harness

To inspect what the LLM actually returns and what Pallium promotes from it, run:

```powershell
.\.venv\Scripts\python.exe -m evals.semantic_runner
```

To run a different batch file:

```powershell
.\.venv\Scripts\python.exe -m evals.semantic_runner --input-file path\to\items.jsonl
```

To speed up larger comparisons with bounded concurrency:

```powershell
.\.venv\Scripts\python.exe -m evals.semantic_runner --prompt-variants baseline,strict_decision_v2_source_aware --max-concurrency 4
```

Defaults:

- input file: [evals/semantic/input/items.jsonl](C:/Dev/rore/Pallium/evals/semantic/input/items.jsonl)
- output runs: `evals/semantic/output/<run-id>/`
- default run id shape: `<suite-name>__<provider>__<model>__<timestamp>`
- default concurrency: `1` (increase with `--max-concurrency` for faster prompt bakeoffs)

Each run writes by default:

- `summary.json`
- `results.jsonl` with one JSON record per input item

Use `--split-output` when you also want one `*.result.json` file per input item for deeper debugging.

Each input line in `items.jsonl` is one normalized source item. Each result record includes:

- the input source item
- the exact prompts used
- raw LLM text
- parsed JSON
- normalized extraction
- final promoted annotations, memory objects, relations, and index entries
- any error details if the LLM path fails

This is intended for debugging first and can later become regression input.

## Test With Bruno

If you prefer request-driven manual testing, open the root `bruno/` collection
in Bruno.

1. Start the API locally.
2. Select the `local` environment.
3. Run `items/Create Item`.
4. Run `query/Query Items`.

The current collection matches the active HTTP surface:

- `POST /items` with explicit event refs for agent-produced messages and artifacts
- `POST /query` returning mixed `memory_hit` and compact `source_hit` results

## Repository Guide

- docs/README.md
  Documentation map and ownership model

- docs/context/
  Stable project truth: vision, architecture, decisions, state

- docs/designs/
  Deeper design threads and analyses

- roadmap/
  Canonical planning workspace for queue, scope, and feature status

- tools/minimap/
  Repo-local planning support

## Planning Model

This repo uses Minimap for roadmap and feature planning. roadmap/ is the
canonical planning surface for active work and sequencing.

## Notes For Contributors

- Keep the core generic.
- Put domain meaning in semantic layers, not in the core.
- Keep memory evidence-backed.
- Prefer additive semantics over destructive rewriting.
- Avoid duplicating source systems of record.

This project uses [Minimap](https://github.com/rore/minimap) for repo-local roadmap and feature planning.
