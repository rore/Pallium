# Getting Started

This is the fastest way to evaluate Pallium as a developer.

Goal for this walkthrough:

- run the local service
- ingest a small sample conversation
- query a repeated question
- query a resumed-work question
- inspect the debug trace

## Prerequisites

- Python 3.12 or newer
- an API key for an OpenAI-compatible provider if you want to use the default
  `agent_conversation_memory` setup

## 1. Set Up The Local Environment

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
Copy-Item pallium.example.toml pallium.local.toml
Copy-Item .env.example .env.local
```

Set `PALLIUM_OPENAI_API_KEY` in `.env.local`.

Optional verification:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 2. Start The Service

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```


## 3. Run The Bundled Sample Flow

In another terminal:

```powershell
.\.venv\Scripts\python.exe examples\agent_memory_simulation.py
```

That script now does four things against the running service:

1. ingests a small agent-mediated conversation with scoped visibility
2. queries a repeated question about a prior decision
3. queries a repeated question about a prior investigation
4. queries resumed-work state and a debug trace

## 4. What You Should See

You should see output that includes:

- ingest responses with created memory object IDs
- a repeated-question query returning compact `memory_hit` and `source_hit`
  cards
- a resumed-work query returning compact work-state context
- a debug response that includes retrieval trace details

You are not looking for perfect prose. You are looking for the shape of the
system:

- selected evidence goes in
- compact memory and evidence cards come back out
- the debug path explains what retrieval did

## 5. Manual Next Step

Once the sample flow makes sense, open the integration guide and map the same
loop onto your own runtime:

- [agent-integration.md](agent-integration.md)
- [privacy-and-visibility.md](privacy-and-visibility.md)

## What You Just Proved

In one short run, you verified that the current repo already ships:

- a local service you can run yourself
- scoped ingest for agent-mediated events
- compact retrieval over memory plus evidence
- resumed-work continuity support in the current slice
- a debuggable retrieval path