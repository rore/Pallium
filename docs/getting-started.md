# Getting Started

Goal: run the local service, try a realistic memory loop, and inspect
Pallium's decisions — in about 10 minutes.

## Prerequisites

- Python 3.12 or 3.13 recommended (3.14 is supported but has known native library issues on Windows)
- An API key for an LLM provider (OpenAI-compatible or Anthropic) if you want
  the full `agent_conversation_memory` setup

To evaluate without a live LLM provider, set
`default_use_case = "demo_agent_memory"` in `pallium.local.toml`. Retrieval
still works; extraction falls back to deterministic behavior.

## 1. Set Up

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev,vector]"
cp pallium.example.toml pallium.local.toml
cp .env.example .env.local
```

Set your LLM API key in `.env.local` (e.g. `PALLIUM_OPENAI_API_KEY` or
`ANTHROPIC_API_KEY`).

See [configuration.md](configuration.md) for the full config surface.

## 2. Start Pallium

```bash
python -m app.run --host 127.0.0.1 --port 8000 --processors 1
```

This starts the API server, one background processor, and one cleaner.

For split-mode (separate processes):

```bash
python -m app.run serve --host 127.0.0.1 --port 8000
python -m app.run processor
python -m app.run cleaner
```

## 3. Run the Harness

In another terminal:

```bash
python -m app.agent_simulation chat-lite
```

`chat-lite` runs a thin-agent loop against the real HTTP endpoints: it ingests
your messages, queries Pallium before each assistant turn, and auto-accepts
replies. Ask repeated questions or resume interrupted work to see memory in
action.

For the operator/debug workflow with accept/edit/discard and artifact capture:

```bash
python -m app.agent_simulation
```

Useful commands:

| Command | Effect |
|---------|--------|
| `/new` | Start a new conversation (enables cross-thread recall) |
| `/debug on` | Show full trace detail |
| `/save demo-run` | Save a replayable JSON session |
| `/replay <path>` | Replay a saved session |
| `/mode chat-lite` | Switch to lightweight auto-accept mode |
| `/mode chat` | Switch to operator/debug mode |
| `/help advanced` | Full command reference |

## 4. What to Look For

A good session looks like this:

1. You ask a question — Pallium ingests it and returns `should_inject: false`
   (no prior memory yet)
2. The agent answers — the reply is stored as evidence
3. You start a new thread (`/new`) and ask a related question — Pallium returns
   `should_inject: true` with a compact memory card carrying forward the
   decision or finding from the earlier thread
4. The debug trace shows why: which retrieval method found the match, what
   routing lane selected it, and why injection was approved

Specifically, you should see:

- user and assistant turns ingested through `POST /items`
- `should_inject` and `decision_reason` on each query
- compact memory cards returned when Pallium has useful carry-forward
- the debug path explaining retrieval, routing, and visibility decisions

You're looking for the shape of the system: selected evidence goes in, compact
memory and evidence cards come back, and only approved carry-forward gets
injected into the agent's prompt.

## 5. Lower-Level HTTP Example

If you want raw HTTP calls without the harness:

```bash
python examples/agent_memory_simulation.py
```

This script shows the ingest and query flow as plain HTTP requests.

## Next Steps

- Demo walkthrough: [examples/demo-session.md](../examples/demo-session.md) — complete session with real API requests and debug trace
- Full config reference: [configuration.md](configuration.md)
- API endpoints and shapes: [http-api.md](http-api.md)
- Wiring into a runtime: [agent-integration.md](agent-integration.md)
- How the system works: [how-it-works.md](how-it-works.md)
