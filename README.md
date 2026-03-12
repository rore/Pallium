![Pallium Banner](assets/logo/pallium_header.png)

# Pallium

Pallium is a local-first memory service for agents.

It lets an agent runtime ingest selected conversation evidence, derive reusable
memory objects such as decisions and investigation outcomes, and later retrieve
compact, evidence-backed results instead of replaying whole transcripts.

Today the project is focused on one concrete product slice:
`agent_conversation_memory`. That slice is about helping an agent stay
oriented across repeated questions, interrupted work, and resumed threads
without turning Pallium into the agent runtime, a vector database, or a
transcript archive.

## Why This Exists

Most agent systems can see the current thread, but they quickly lose:

- prior decisions and why they were made
- investigation outcomes and the evidence behind them
- resumed-work state such as progress, blockers, and next steps
- safe separation between public and private memory

Pallium is the layer that stores those things in a reusable form.

## What You Should Understand In 60 Seconds

Pallium sits beside an agent, not inside the model:

1. your runtime decides which events are worth remembering
2. Pallium stores those source items and derives memory from them
3. your runtime queries Pallium when it needs prior context
4. Pallium returns compact `memory_hit` and `source_hit` cards with evidence refs

Current shipped API:

- `POST /items`
- `POST /query`
- `POST /query/debug`

Current shipped memory types:

- `decision`
- `investigation_outcome`
- `thread_summary`
- `task_checkpoint`
- `pattern_memory`
- `continuity_memory`
- fallback `discussion_summary`

## What Pallium Does Today

Implemented and committed in the repo:

- one local-first FastAPI service with SQLite-backed storage
- a generic core with explicit `SourceItem`, `Annotation`, `Relation`,
  `IndexEntry`, and `MemoryObject` primitives
- semantic package entry points for `demo_agent_memory`,
  `llm_agent_memory`, and `agent_conversation_memory`
- OpenAI-compatible and Anthropic-style LLM provider adapters with bounded
  retries, backoff, request-id capture, and concurrency limits
- lexical retrieval over both source evidence and promoted memory
- compact source hits instead of raw transcript replay by default
- routed retrieval inside `agent_conversation_memory` across higher-level
  memory, lower-level memory, and source evidence
- debug retrieval trace through `POST /query/debug`
- thread aggregation and bounded higher-level memory consolidation
- privacy-aware `visibility_context` enforcement for the
  `agent_conversation_memory` package
- eval and benchmark suites for semantic extraction, recurring questions,
  work resumption, routed retrieval, consolidation strategies, and public-corpus
  validation

## Current Product Boundary

The current package is deliberately narrow.

Good fit:

- agent-mediated user messages
- final assistant outputs
- selected assistant-originated work artifacts:
  `tool_use_summary` and `todo_snapshot`
- repeated questions, cross-thread recall, and resumed-work continuity

Out of scope for the current slice:

- ambient workplace chat that never flowed through an agent
- raw tool logs, raw MCP events, and exhaustive runtime notifications
- broad workspace search or org-wide knowledge sync
- cross-container shared memory
- vector retrieval and hybrid fusion

## What Pallium Is Not

Pallium is not:

- an agent runtime
- a workflow engine
- a connector framework as its core identity
- a system-of-record database
- a transcript archive or raw tool-log warehouse

## Quick Start

The commands below use PowerShell. Translate them for your shell if needed.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
Copy-Item pallium.example.toml pallium.local.toml
Copy-Item .env.example .env.local
```

Optional verification:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Set an API key in `.env.local`, then run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
.\.venv\Scripts\python.exe examples\agent_memory_simulation.py
```

If you want to bring up the service without a live LLM provider, set
`default_use_case = "demo_agent_memory"` in `pallium.local.toml`.

## Minimal API Flow

Example ingest request:

```json
{
  "source_type": "assistant_artifact",
  "source_id": "artifact-002",
  "content_type": "text/plain",
  "content": "Decision: use item event time for reservation ordering to avoid missed hold updates during sync delays.",
  "artifact_kind": "assistant_output",
  "role": "assistant",
  "container_ref": "chat:library-help",
  "thread_ref": "chat:library-help:1730000000.000100",
  "session_ref": "agent-session-1",
  "actor_ref": "agent:assistant",
  "source_ref": "https://example.test/chat/artifact-002",
  "visibility_context": {
    "kind": "limited",
    "id": "library-help"
  }
}
```

Example query request:

```json
{
  "text": "why did we choose item event time for reservation ordering?",
  "limit": 5,
  "container_ref": "chat:library-help",
  "visibility_context": {
    "kind": "limited",
    "id": "library-help"
  }
}
```

Result shape:

- `memory_hit`: compact promoted memory such as a `decision` or `task_checkpoint`
- `source_hit`: compact evidence card with refs and excerpt

Use `POST /query/debug` when you need lexical hit trace, routed-layer choice, or
visibility exclusion debugging.

## Integration Model

An agent should use Pallium as a bounded memory sidecar:

- write to Pallium when the runtime sees a user message, final assistant answer,
  or an explicit assistant work artifact worth remembering
- query Pallium when answering repeated questions, resuming work, or starting a
  new related thread
- keep `source_id` stable so repeated ingest stays idempotent
- keep the source of truth outside Pallium; it stores selected copies plus
  derived memory

The current package expects explicit runtime curation. Pallium is not designed
to ingest every event your agent sees.

See [docs/agent-integration.md](docs/agent-integration.md) for the practical
integration guide.

## Privacy And Visibility

`agent_conversation_memory` is scope-aware.

The package uses a consumer-supplied `visibility_context` on ingest and query:

- `public` queries can see `public`
- `limited:X` queries can see `public` and `limited:X`
- `user:U1` queries can see `public` and `user:U1`

Important current behavior:

- missing query visibility fails closed
- missing ingest visibility is stored but not promoted or returned in normal
  scoped queries
- thread aggregation and higher-level consolidation do not cross visibility
  contexts
- `container_ref`, `thread_ref`, and `session_ref` are locality metadata, not
  the privacy model

See [docs/privacy-and-visibility.md](docs/privacy-and-visibility.md) for the
full contract.

## Status And Roadmap

This repository already ships the first end-to-end product slice, but it is not
claiming to be finished.

Current next step:

- one canonical integration-readiness scenario that proves resumed-work value
  and fail-closed public/private separation together

Planned but not yet shipped:

- vector retrieval behind the retrieval boundary
- explicit hybrid lexical plus vector fusion
- explicit shared-memory derivation
- cross-container bounded memory

See [roadmap/board.md](roadmap/board.md) and [roadmap/scope.md](roadmap/scope.md).

## Documentation

Start here:

- [docs/overview.md](docs/overview.md)
- [docs/agent-integration.md](docs/agent-integration.md)
- [docs/privacy-and-visibility.md](docs/privacy-and-visibility.md)

Stable context:

- [docs/context/vision.md](docs/context/vision.md)
- [docs/context/architecture.md](docs/context/architecture.md)
- [docs/context/state.md](docs/context/state.md)

Deeper design threads:

- [docs/designs/README.md](docs/designs/README.md)