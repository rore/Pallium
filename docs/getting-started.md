# Getting Started

This is the fastest way to evaluate Pallium as a developer.

Goal for this walkthrough:

- run the local service
- ingest a small sample conversation
- query a repeated question
- query a resumed-work question
- inspect the debug trace

A typical quick check looks like this:

- ingest a decision such as "use item event time for reservation ordering"
- ask "why did we choose item event time?"
- confirm that Pallium returns a compact decision memory plus supporting
  evidence
- then ask a resumed-work question and inspect the debug trace

## Prerequisites

- Python 3.12 or newer
- an API key for an OpenAI-compatible provider if you want to use the default
  `agent_conversation_memory` setup

If you want to evaluate the service without a live LLM provider first, switch
`default_use_case = "demo_agent_memory"` in `pallium.local.toml`. The behavior
is simpler, but the HTTP flow is the same.

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

You should see:

- ingest succeeding for the sample conversation
- repeated-question queries returning compact memory and evidence cards
- resumed-work queries returning useful prior state
- debug output showing retrieval and visibility behavior

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