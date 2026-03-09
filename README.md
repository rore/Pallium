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
- one semantic layer interface with a simple in-repo plugin pattern
- one storage layer
- one mixed retrieval path over memory and source evidence
- one deterministic typed-memory path for `decision`
- one simulated generic agent consumer for end-to-end proof

The current top-level architecture is:

1. API layer
2. Generic core
3. Semantic layer
4. Storage layer
5. Retrieval layer
6. Optional background jobs

## Core Concepts

The generic core currently centers on five primitives:

- SourceItem
- Annotation
- Relation
- IndexEntry
- MemoryObject

The core owns storage and orchestration. Semantic layers define meaning.

## Tiered Memory

Tiered memory is an intended extension, not part of the current executable slice.

The idea is to periodically consolidate lower-level memory into higher-level
reusable memory objects such as topic summaries or recurring patterns, while
keeping all lower-level evidence intact.

## Status

The first typed-memory milestone is implemented and verified.

What exists now:

- Python project scaffold
- FastAPI application wiring
- generic core models and orchestration service
- semantic plugin interface plus a deterministic demo plugin
- storage abstraction plus SQLite implementation
- mixed retrieval over promoted memory and raw source evidence
- deterministic promotion of `decision` memory objects and fallback `discussion_summary`
- simulation script, Bruno collection, and pytest coverage
- project context, designs, and roadmap docs

Verified locally:

- pytest passes
- the live HTTP flow returns decision memory hits, discussion-summary hits, and source hits with evidence

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

## Test With Bruno

If you prefer request-driven manual testing, open the root `bruno/` collection
in Bruno.

1. Start the API locally:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

2. Select the `local` environment.
3. Run `items/Create Item`.
4. Run `query/Query Items`.

The current collection matches the active HTTP surface:

- `POST /items`
- `POST /query` returning mixed `memory_hit` and `source_hit` results

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
