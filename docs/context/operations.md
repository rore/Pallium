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

## SQLite database operations

Both SQLite files use the same lifecycle: WAL, auto_vacuum=INCREMENTAL, and a bounded connection busy timeout. Relay writes use only the Relay file, so a long ingestion transaction in the main file does not hold the Relay writer lock. Each file must still be backed up, checked, and restored as a pair; never mix files from different snapshot generations.

The first split upgrade is supported only while the previous service process tree is fully stopped. Use the platform service wrapper (on Windows, scripts/restart-service.ps1; on Unix, stop the service before starting the new version), then verify /health, /status, and /debug/queue/health. The migration copies legacy Relay sessions, messages, and deliveries transactionally and records a source/target marker. Re-running is safe before completion; after the marker, a missing or mismatched Relay file fails closed. Legacy Relay rows remain in the main file as rollback evidence, but rollback after new Relay writes is not automatic. Do not restart an old binary after the split: older code does not understand the marker and is outside the supported upgrade path; if it writes to the legacy tables, stop both versions and reconcile before continuing.

## Developing integrations without leaving stale local installs

Claude Code and Codex setup commands write absolute checkout and Python paths into the
host's MCP and hook configuration. The OpenCode global loader likewise points
at a concrete plugin file. Treat a temporary worktree as a build/test location,
not as the long-lived installation source.

When moving an installation from a worktree back to the primary checkout:

1. Preserve dirty work in a named stash or branch, restore the primary checkout
   to clean, current `main`, and keep the old worktree until migration finishes.
2. Run each supported uninstaller **from the old checkout's working directory**,
   then run setup from the primary checkout. Hook removal is path-specific;
   setup or uninstall from the new path alone can leave both old and new hooks.
3. Confirm Claude's MCP plus hooks and Codex's MCP, hooks, and
   `pallium-relay.config.toml` contain only primary-checkout paths. Confirm the
   OpenCode config still registers its loader, the loader points to the primary
   plugin, and its MCP URL uses the installed service port.
4. Restart already-open agent hosts when their MCP or hook configuration must be
   reloaded. New sessions use the new installation; existing MCP subprocesses
   can keep the old executable until their host restarts.

Changing integration or service code normally requires updating the stable
checkout and restarting the installed service, not reinstalling its scheduled
task. On Windows, always use `scripts/restart-service.ps1`. The installed
launcher must use a dependency-complete Python and the supported
`python -m app.run service run --port <port>` path: `service run` applies the
managed `~/.pallium/config/.env` and service configuration. Do not use the
`scripts/install-service.ps1` merely to repoint development code or run a
service from a temporary worktree.

After any migration, verify the actual installed state rather than trusting
setup output:

- primary checkout is clean `main` at `origin/main`
- no host config or service launcher refers to the retired worktree
- `claude mcp get pallium` reports connected
- `codex --profile pallium-relay mcp list` resolves Pallium
- the OpenCode plugin suite passes from the primary checkout
- `/health`, `/status`, and `/debug/queue/health` respond; specifically check
  `embedding_provider_ok` and `ingestion.status`

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
| `/status` | `ingestion.status` | `degraded` = an enabled package declares a provider credential that did not resolve. `issues` names the package, provider, and configured environment-variable name, never the secret. |

`degraded` stays HTTP 200 on purpose: the service is functional (lexical retrieval
still works), so orchestration should not hard-fail. The signal is the `status`
and `degraded_reasons` fields, and the dashboard badge turns non-green.

## Ingestion credential readiness

A declared `api_key_env` or `api_key_file` that resolves to no value makes
`/status.ingestion.status` degraded and the dashboard non-green. The service
keeps Relay and inspection available but starts with ingestion workers paused, and
points to the managed `.pallium/config/.env` file. Once the credential is
repaired and the service restarted, terminal items do not retry by themselves; use the
loopback-only `POST /debug/queue/retry-failed` operation for the matching
failure category.

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
