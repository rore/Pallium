# MCP Server for Agent Awareness — Design Spec

**Date:** 2026-04-07
**Status:** Draft

---

## Problem

Pallium currently integrates with agent runtimes as a backend-only service: the runtime queries Pallium before each turn and ingests artifacts after, but the LLM has zero awareness of the memory system. Memory blocks are prepended to the user message as context — the LLM can't distinguish them from user text, can't search for specific memories, can't debug retrieval failures, and can't explicitly store artifacts.

Users want to ask "did you use the memory about X?" or "why don't you remember Y?" and get meaningful answers. This requires the LLM to know the memory system exists and to have tools for interacting with it.

## Goals

1. Ship an MCP server in Pallium that exposes memory tools to any MCP-compatible agent.
2. Expose three tools: explicit query, retrieval debug, and artifact ingest.
3. Keep the MCP server thin — a stdio process that wraps Pallium's existing HTTP API.
4. Support environment-based context defaults (container, thread, actor, visibility) with optional per-call overrides.
5. Self-gate gracefully when Pallium is not configured (defense-in-depth alongside conditional registration by the integrator).
6. Document the integration contract so any agent runtime can use it.

## Non-Goals

- Lifecycle tools (pin, forget, snooze) — future work once the read path proves useful.
- Explicit "remember" bypass of semantic extraction — ingest uses the existing pipeline.
- Custom MCP transport (SSE, streamable-HTTP) — stdio is sufficient.
- Changes to Pallium's core service, retrieval, or storage layers.
- Integrator-specific wiring (downstream runtimes own their own registration, env var injection, and prompt assembly).

---

## Architecture

### Module Structure

New `app/mcp/` subpackage (transport adapter, sibling to the HTTP API in `api/`):

```
app/mcp/
  __init__.py
  server.py      # MCP server setup, tool registration
  client.py      # Async HTTP client wrapping Pallium's REST API
  context.py     # Environment-based context resolution
```

The MCP server is a transport adapter — it serves the same role for MCP that `api/` serves for HTTP. It lives under `app/` because it is a separate process entry point, not part of the FastAPI application.

### Runtime Model

The MCP server is a separate entry point, not part of the FastAPI server. It is a thin stdio process that makes HTTP calls to the already-running Pallium HTTP server.

```
┌─────────────┐    stdio    ┌──────────────────┐    HTTP    ┌──────────────────┐
│  Agent       │◄──────────►│ pallium mcp      │──────────►│ pallium serve    │
│  (MCP client)│            │ (stdio, ephemeral)│           │ (long-lived)     │
└─────────────┘            └──────────────────┘           └──────────────────┘
```

The MCP server has no direct dependency on Pallium's core code — no SQLAlchemy, no embedding models, no semantic packages. It depends only on the `mcp` Python SDK (FastMCP) and `httpx`.

### Entry Point

`python -m app.run mcp`

Adds an `mcp` subcommand to the existing CLI entry point. Reads configuration from environment variables at startup:

| Variable | Required | Purpose |
|----------|----------|---------|
| `PALLIUM_BASE_URL` | Yes | Pallium HTTP server URL (e.g. `http://127.0.0.1:8000`) |
| `PALLIUM_CONTAINER_REF` | No | Default container scope |
| `PALLIUM_THREAD_REF` | No | Default thread scope |
| `PALLIUM_ACTOR_REF` | No | Default actor scope |
| `PALLIUM_VISIBILITY` | No | Default visibility level |

### Self-Gating

If `PALLIUM_BASE_URL` is not set, the MCP server starts but all tools return a clear message:

```
Pallium memory system is not configured. No memory tools available.
```

This is defense-in-depth: integrators should conditionally register the MCP server (only when Pallium is enabled), but if the entry exists without proper configuration, the server degrades gracefully with a clear diagnostic rather than failing silently or producing confusing errors.

---

## Tools

### Context Resolution

All three tools accept optional scope parameters that override environment defaults:

| Parameter | Type | Default |
|-----------|------|---------|
| `container_ref` | string, optional | `PALLIUM_CONTAINER_REF` env var |
| `thread_ref` | string, optional | `PALLIUM_THREAD_REF` env var |
| `actor_ref` | string, optional | `PALLIUM_ACTOR_REF` env var |
| `visibility` | string, optional | `PALLIUM_VISIBILITY` env var |

Resolution order: **explicit parameter > environment variable > omitted**.

Integrating runtimes typically set the env vars per-message so the LLM never needs to pass them. Direct users or other integrators can pass them explicitly.

### `pallium_query`

Explicit memory search when automatic injection is missing something.

**Parameters:**
- `query` (string, required) — search text
- `limit` (int, optional, default 5) — max results
- `container_ref`, `thread_ref`, `actor_ref`, `visibility` (optional, see above)

**Maps to:** `POST /query`

**Returns:** JSON-as-text (pretty-printed). Passes through Pallium's `QueryResponse` verbatim: `results` array with score, type, evidence, excerpt; `should_inject` flag; `decision_reason`; `injectable_blocks`.

### `pallium_query_debug`

Investigate retrieval — why a memory was or wasn't found.

**Parameters:**
- `query` (string, required) — search text
- `container_ref`, `thread_ref`, `actor_ref`, `visibility` (optional, see above)

**Maps to:** `POST /query/debug`

**Returns:** JSON-as-text (pretty-printed). Passes through Pallium's `QueryDebugResponse` verbatim: everything from `QueryResponse` plus `trace` with retrieval stages, candidate scores, visibility filtering, fusion trace, and injection decision reasoning.

### `pallium_ingest`

Store a conversation artifact for processing through Pallium's semantic pipeline.

**Parameters:**
- `content` (string, required) — text to store
- `source_type` (string, optional, default `"agent_artifact"`) — upstream system name
- `source_id` (string, optional, auto-generated UUID) — unique stable ID
- `artifact_kind` (string, optional) — one of: `message`, `assistant_output`, `tool_use_summary`, `todo_snapshot`, `notification`
- `role` (string, optional) — `"user"` or `"assistant"`
- `container_ref`, `thread_ref`, `actor_ref`, `visibility` (optional, see above)

**Maps to:** `POST /items` (single-item array)

**Returns:** JSON-as-text. Passes through Pallium's `ItemCreateResponse` verbatim: `source_item_id`, `processing_status`, `memory_object_ids`.

### Ingest Safety

The ingest tool does not create memory objects directly. It submits artifacts to Pallium's existing semantic processing pipeline — the same pipeline that processes artifacts from any runtime integration. The pipeline decides what (if anything) to extract based on the active semantic packages, extraction rules, and quality thresholds. If the content doesn't contain extractable decisions, outcomes, or other memory-worthy material, the pipeline produces nothing.

This means the semantic pipeline is the guardrail, not the MCP tool. The LLM cannot:
- Create memory objects directly (only submit artifacts for processing)
- Bypass extraction quality thresholds
- Override semantic package rules

The integrating runtime's agent instructions should reinforce this by telling the LLM not to ingest routine conversation (since the runtime already ingests outputs automatically), but the system-level safety does not depend on the LLM following those instructions.

### Response Format

All tools return responses as `{ type: "text", text: "<pretty-printed JSON>" }`, following the common MCP pattern for data-rich tools. The MCP server passes through Pallium's HTTP API responses verbatim as pretty-printed JSON. No field removal, no flattening, no transformation. The API response structure is the contract — if the response shape needs improvement for LLM consumption, that is addressed in the HTTP API layer, not in the transport adapter.

---

## Integration Guide

### What Pallium Provides

- The MCP server as a subcommand: `python -m app.run mcp`
- Environment variable contract (see Entry Point table above)
- This design spec as the integration reference

### What the Integrating Runtime Does

The integrating agent runtime is responsible for:

1. **Conditional registration**: Register the Pallium MCP server in the agent's tool configuration only when Pallium is enabled. The MCP entry should reference `python -m app.run mcp` with a working directory or path that resolves to the Pallium installation.

2. **Environment variables**: Inject `PALLIUM_BASE_URL` and scope variables (`PALLIUM_CONTAINER_REF`, `PALLIUM_THREAD_REF`, `PALLIUM_ACTOR_REF`, `PALLIUM_VISIBILITY`) into the MCP subprocess environment. Values are dynamic per-session/per-message depending on the runtime's session model.

3. **Agent instructions**: Include a prompt block that teaches the LLM about the memory system's two-tier model (automatic injection for ~90% of turns, explicit tools for the rest) and when to use each tool. An example prompt block:

```markdown
## Memory

You have access to a memory system that remembers decisions, investigation
outcomes, and context from previous conversations. It works in two ways:

**Automatic (most turns):** Relevant memories are injected into the conversation
context automatically. Trust this — it's pre-selected for relevance. You don't
need to do anything.

**Explicit tools (when automatic isn't enough):**
- `pallium_query` — Search memory when the injected context is missing
  something specific. Example: user asks about a past decision that wasn't
  auto-injected.
- `pallium_query_debug` — Investigate retrieval. Use when a user asks
  "why don't you remember X?" or when you suspect a memory should exist
  but wasn't injected.
- `pallium_ingest` — Store an artifact for memory processing. Use when the
  user explicitly asks you to remember something, or to record a
  decision/outcome for future reference.

**When NOT to use tools:**
- Don't query on every turn — automatic injection handles most cases.
- Don't re-query for something already in the injected context.
- Don't ingest routine conversation — the integration layer already ingests
  your outputs automatically.
```

4. **Enable/disable mechanism**: Provide a way to toggle the MCP registration, env vars, and prompt block together. The mechanism is runtime-specific (CLI command, config flag, etc.).

---

## Dependencies

**Pallium-side:**
- `mcp[cli]` Python package (FastMCP) — new dependency
- `httpx` — already in Pallium's deps

---

## Testing

- **Unit tests** for `app/mcp/client.py` — mock HTTP responses, verify request formatting and context resolution
- **Unit tests** for `app/mcp/context.py` — env var reading, override merge logic
- **Integration test** — start Pallium HTTP server, start MCP server, issue tool calls, verify end-to-end response matches HTTP API response exactly
- **Self-gating test** — MCP server without `PALLIUM_BASE_URL` returns graceful message
- **Passthrough test** — verify MCP response is identical to HTTP API response (no transformation)

---

## Documentation Updates

- `docs/context/architecture.md` — note MCP transport adapter under the API layer
- `docs/http-api.md` or new `docs/mcp-integration.md` — integration reference for runtime developers

---

## Future Extensions

- **Lifecycle tools** (pin, forget, snooze) once the read path proves useful
- **Explicit remember** that bypasses semantic extraction for user-requested memories
- **Streaming responses** for large result sets
- **HTTP MCP transport** if per-message cold start becomes a concern
