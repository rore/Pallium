# Operations

How the Pallium service runs and how to read its health. Machine-specific launch
details (paths, keys, restart commands) live in operator notes, not here.

## Service model

Pallium runs as a long-lived local service, independent of any one repo or agent
session. A supervisor process starts the HTTP **api**, the async **processor**
(ingest → memory), the **cleaner** (retention), and the **MCP** endpoint. State is
a single SQLite DB plus an on-disk vector index.

The service is **trusted-local**: no auth layer. Identity fields (`container_ref`,
`actor_ref`, `session_id`) are for attribution and visibility scoping, not
authorization.

Codex and Claude hooks expose the host's active task as a compact injected
`thread_ref`; deliberate historical search and expansion must pass it so lookup
events can be joined to later work. It always names the requester, never the
historical source, and grants no access. If the host supplies no task identity,
Pallium leaves attribution absent rather than guessing or writing `unknown`. The
marker uses the existing injection character budget.

## Health signals

Two endpoints report liveness. Read them together — a 200 alone does not mean
fully functional. `/health` is the liveness endpoint (always available);
`/status` provides diagnostics and is **SQLite-only** — it returns HTTP 501 when
another storage backend is configured.

| Endpoint | Field | Meaning |
|----------|-------|---------|
| `/health` | `status: ok` | Lifespan complete, vector index ready (or intentionally off). |
| `/health` | `status: initializing` (503) | Still starting — schema migration / vector load in progress. |
| `/health` | `status: degraded` (200) | Reachable but **impaired**: vector was expected but the embedding provider failed to initialize. See `degraded_reasons`. |
| `/status` | `vector_expected` | Config intends vector search to run. |
| `/status` | `embedding_provider_ok` | `false` = vector expected but the embedding provider did not load. |

`degraded` stays HTTP 200 on purpose: the service is functional (lexical retrieval
still works), so orchestration should not hard-fail. The signal is the `status`
and `degraded_reasons` fields, and the dashboard badge turns non-green.

## The embedding-provider gotcha

The most common silent degrade: vector search is enabled in config, but the
runtime the service launched under is missing the embedding provider's native
dependency (e.g. `onnxruntime`). The provider fails to initialize, the vector
index is never built, and **semantic search is silently disabled** — lexical-only
results, often near-empty for conceptual queries.

Before this signal existed, `/health` and `/status` stayed green in that state.
Now `embedding_provider_ok` goes `false` and `/health` reports `degraded`.

**When search returns too little:** check `embedding_provider_ok` first. If it is
`false`, the fix is the launch environment (install the embedding dependency into
the runtime the service actually uses), not the query or the data.
