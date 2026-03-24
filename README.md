![Pallium Banner](assets/logo/pallium_header.png)

# Pallium

Local-first memory sidecar for AI agents. Stores selected evidence, derives
compact memory, returns evidence-backed cards for follow-up questions and
resumed work.

## The Problem

Agents forget why decisions were made, lose investigation outcomes, and
struggle to resume interrupted work. Transcript replay is expensive and noisy.
Prompt summaries lose evidence. Vector search alone doesn't give you structured
conclusions or scoped visibility.

Pallium preserves reusable knowledge created during the agent's own work —
decisions, findings, constraints, and work-state checkpoints — linked back to
supporting evidence.

## Quick Example

Store a decision the agent made:

```bash
curl -X POST http://localhost:8000/items -H 'Content-Type: application/json' -d '[{
  "source_type": "chat_message",
  "source_id": "msg-042",
  "content_type": "text/plain",
  "content": "Decision: use item event time for reservation ordering instead of wall clock. Reason: event time reflects actual hold sequence and avoids timezone drift across regional deployments.",
  "artifact_kind": "assistant_output",
  "role": "assistant",
  "container_ref": "channel:catalog-sync",
  "visibility": "container",
  "thread_ref": "thread-17"
}]'
```

Later, ask why:

```bash
curl -X POST http://localhost:8000/query -H 'Content-Type: application/json' -d '{
  "text": "Why did we choose event time for reservation ordering?",
  "container_ref": "channel:catalog-sync",
  "visibility": "container"
}'
```

Pallium returns:

```json
{
  "should_inject": true,
  "decision_reason": "carry_forward_available",
  "injectable_blocks": [
    {
      "block_type": "memory_hit",
      "title": "decision",
      "text": "Use item event time for reservation ordering instead of wall clock.",
      "memory_type": "decision"
    }
  ],
  "results": [
    {
      "result_kind": "memory_hit",
      "type": "decision",
      "score": 850,
      "container_ref": "channel:catalog-sync",
      "visibility": "container",
      "retrieval_source": "lexical"
    }
  ]
}
```

## Getting Started

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev,vector]"
cp pallium.example.toml pallium.local.toml
cp .env.example .env.local
# Set your LLM API key in .env.local
```

Start the service and try the interactive harness:

```bash
python -m app.run --host 127.0.0.1 --port 8000 --processors 1
# In another terminal:
python -m app.agent_simulation chat-lite
```

The harness runs a thin-agent loop against the real HTTP endpoints — ask
repeated questions or resume interrupted work and inspect Pallium's memory
decisions.

See [docs/getting-started.md](docs/getting-started.md) for the full
walkthrough.

## How It Works

1. **Ingest** — selected evidence goes in via `POST /items` (not everything, just high-value events)
2. **Process** — background workers extract structured memory (decisions, findings, checkpoints) and embed for retrieval
3. **Query** — `POST /query` retrieves compact memory + source evidence, scoped by visibility, with an injection decision
4. **Combined** — `POST /item-and-query` does ingest + query in one call (recommended for the common per-message pattern)
5. **Debug** — `POST /query/debug` or `POST /item-and-query/debug` exposes the full retrieval and routing trace

Retrieval combines lexical search, vector similarity, and hybrid RRF fusion.
The query path is deterministic by default, with selective LLM-assisted
disambiguation only for bounded ambiguous cases.

See [docs/how-it-works.md](docs/how-it-works.md) for the full model.

## Scope

Good fit:
- agent-mediated conversations and follow-up questions
- resumed investigations or implementation work
- scoped public/private memory boundaries
- inspectable retrieval when results look wrong

Not a fit:
- transcript archive or raw event storage
- broad workspace or org-wide knowledge search
- agent runtime or workflow engine
- general-purpose vector database

## Documentation

- [Getting Started](docs/getting-started.md) — local setup to first query
- [How It Works](docs/how-it-works.md) — architecture, memory model, retrieval
- [HTTP API](docs/http-api.md) — endpoints, request/response shapes, examples
- [Configuration](docs/configuration.md) — providers, packages, tuning knobs
- [Agent Integration](docs/agent-integration.md) — wiring Pallium into a runtime
- [Integration Example](docs/integration-example.md) — Slack agent walkthrough with code
- [Privacy and Visibility](docs/privacy-and-visibility.md) — scoped memory boundaries
