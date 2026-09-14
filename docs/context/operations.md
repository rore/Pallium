# Operations

How the Pallium service runs and how to read its health. Machine-specific launch
details (paths, keys, restart commands) live in operator notes, not here.

## Service model

Pallium runs as a long-lived local service, independent of any one repo or agent
session. A supervisor process starts the HTTP **api**, the async **processor**
(ingest → memory), the **cleaner** (retention), and the **MCP** endpoint. State is
a main SQLite DB, an isolated Relay SQLite DB, plus an on-disk vector index.

The service is **trusted-local**: no auth layer. Identity fields (`container_ref`,
`actor_ref`, `session_id`) are for attribution and visibility scoping, not
authorization.

Codex and Claude hooks expose the host's active task as a compact injected
`thread_ref`; deliberate historical search and expansion must pass it so lookup
events can be joined to later work. It always names the requester, never the
historical source, and grants no access. If the host supplies no task identity,
Pallium leaves attribution absent rather than guessing or writing `unknown`. The
marker uses the existing injection character budget.

## Linux user service

The Linux implementation uses one `systemd --user` unit,
`~/.config/systemd/user/pallium.service`. The public
`pallium service install|status|start|stop|restart|uninstall` commands are the
lifecycle authority; the shipped `.sh` wrappers delegate to those commands
instead of generating a second unit form. Manager failures are errors, and
install, start, and restart return success only after `/health`, `/status`,
and `/debug/queue/health` are ready.

There is one Pallium unit per Linux user. Every lifecycle command must use the
same `--home`; installing a different home fails rather than silently
retargeting the unit. Uninstall preserves data by default. `--remove-data` accepts only the default home with its exact managed-home marker
written by install. Custom homes are always preserved and must be removed manually
after inspection; filesystem root and the user home are always refused.

Live qualification covers Ubuntu 24.04 under WSL2 with systemd enabled:
install, idempotent install, status, stop/start, restart, crash recovery,
occupied-port failure, missing unit, custom port, spaces/Unicode home, wrapper
delegation, uninstall, safe data removal, and named-distro restart. Linger is
not changed. When WSL stops the distro, the Linux service is also stopped; the
enabled unit starts and becomes ready when the Ubuntu user session starts
again. This is WSL qualification, not a live claim for every Linux distribution
or for macOS.

## SQLite database operations

Both SQLite files use the same lifecycle: WAL, auto_vacuum=INCREMENTAL, and a bounded connection busy timeout. Relay writes use only the Relay file, so a long ingestion transaction in the main file does not hold the Relay writer lock. Each file must still be backed up, checked, and restored as a pair; never mix files from different snapshot generations.

Persistent `auto_vacuum` and WAL modes are initialized once under the schema lock on an autocommit connection. Pooled connections set only their bounded busy timeout before ordinary work. Incremental-vacuum/checkpoint maintenance temporarily fails fast and restores the connection's prior timeout, so a live reader defers truncation instead of holding a worker for the full busy window.

Only the current Relay schema is supported. Keep the main and Relay SQLite files together, back up and restore them as a paired snapshot generation, and verify /health, /status, and /debug/queue/health after service restart. A partial live pair or a database missing required current Relay columns fails closed without being rewritten.

## Relay control-plane resilience

Relay storage calls use a four-operation AnyIO capacity limiter independent of the
default synchronous route pool, and `/health` stays on the event loop. Client
cancellation does not cancel an already-running SQLite operation; service shutdown
waits for active Relay operations before closing either database. Slow and busy
server operations log only the static operation name, outcome, and duration. Hook
client failures log method, fixed path, duration, and exception type; no payload or
scope identifiers are logged.

Relay MCP clients retry connection establishment failures and structured `relay_busy` responses within one bounded attempt/time budget for reads and explicitly idempotent send, reply, and acknowledgement operations. Read, write, protocol, cancellation, and ambiguous post-acceptance failures are not retried. Exhausted transport and HTTP failures are returned as bounded, redacted MCP tool errors (`isError=true`), not successful string payloads.

Claude Code and Codex hooks persist each exact Relay scope-transition intent before HTTP and serialize registration under the existing per-session lock. `/relay/turn` moves only the supplied endpoint from the supplied source generation; retries recognize exactly one committed generation step. No global session inference or destination takeover occurs. Endpoint aliases, work references, pending/claimed deliveries, and delivery audit snapshots survive a confirmed move. ACK wake rearm resolves the endpoint's live scope rather than the delivery's historical scope snapshot.

The service reconciliation loop scans eligible never-claimed pending deliveries and
expired claims at startup and every 30 seconds, then dispatches through the existing
runtime adapter without claiming early. Codex confirmed or ambiguous native wake
submission retains the oldest per-session
trigger without blind retry because native queue writes are not idempotent. Exact
ACK, MCP ACK, or atomic reply releases that delivery's durable ownership. Startup
and send-time reconciliation remove only missing deliveries or exact
endpoint-matching terminal reservations; pending, active claims, endpoint
mismatches, and uncertain reads keep their fences. Service restart reloads those
durable reservations before reconstructing pending work, preventing blind
resubmission of accepted or uncertain prompts. An exact
internal Codex wake is excluded from deduplication and memory ingestion. The native
prompt can remain model-visible when no delivery block accompanies it, so it carries
the exact delivery ID for nonmutating trace inspection. Ordinary user prompts remain
fail-open.

This protects concurrent users inside the supported single-Uvicorn-process service.
Horizontal multi-process wake dispatch is not yet qualified because recovery
coalescing is process-local; add durable cross-process wake-attempt reservation when
a multi-process deployment is introduced.
## Developing integrations without leaving stale local installs

Claude Code and Codex setup commands write absolute checkout and Python paths into the
host's MCP and hook configuration. The OpenCode global loader likewise points
at a concrete plugin file. Treat a temporary worktree as a build/test location,
not as the long-lived installation source.

When moving an installation from a worktree back to the primary checkout:

1. Preserve dirty work in a named stash or branch, restore the primary checkout
   to clean, current `main`, and keep the old worktree until migration finishes.
2. For Claude Code, run the uninstaller **from the old checkout's working
   directory**, then run setup from the primary checkout; its hook removal is
   path-specific. Current Codex setup repairs missing old sources automatically
   but refuses to replace hooks from another live checkout without explicit
   intent. For a deliberate Codex move, run setup from the destination checkout
   with `--replace-existing-checkout`; this reconciles stale registrations and
   repoints its MCP server. With older Pallium versions, uninstall Codex from
   the old checkout first.
3. Confirm Claude's MCP plus hooks and Codex's MCP, hooks, and
   `pallium-relay.config.toml` contain only primary-checkout paths. Confirm the
   OpenCode config still registers its loader, the loader points to the primary
   plugin, and its MCP URL uses the installed service port.
4. Restart already-open agent hosts when their MCP or hook configuration must be
   reloaded. New sessions use the new installation; existing MCP subprocesses
   can keep the old executable until their host restarts.

Changing integration or service code normally requires updating the stable
checkout and restarting the installed service, not reinstalling its scheduled
task. On Windows, always use `scripts/restart-service.ps1`. It validates the
registered VBS, interpreter, optional working directory, configured port, and
`app.run` imports before stopping a healthy process tree. After launch it reports
success only when `/health`, `/status`, and `/debug/queue/health` satisfy their
documented readiness contracts; failures name the last check and Pallium log.
Queue health is a live database query and may use up to ten seconds; health and
status remain capped at two seconds, and every request is clipped to the one
overall readiness deadline. The default readiness budget is three minutes; an explicit
`-ReadinessTimeoutSeconds` value keeps its exact finite deadline.
For offline Relay endpoint repair, first start the upgraded service once so it creates the repair ledger, then run `scripts/restart-service.ps1 -StopOnly`. The wrapper stops the installed task without starting it again and fails if the task, listener, or managed process tree cannot be conclusively drained.

Create a disposition file that classifies every live repairable delivery on the source endpoints: pending deliveries plus claimed deliveries whose finite lease has expired. An expired claim may only be `suppress`; `adopt`, active claims, missing claim tokens, and missing or malformed leases fail closed.

```json
[
  {"delivery_id": "relay-delivery-...", "disposition": "suppress"},
  {"delivery_id": "relay-delivery-...", "disposition": "adopt"}
]
```

Generate the review manifest against the installed Relay database. Supply the service and hooks' exact effective Claude wake directory explicitly; never infer it from the service home. Supply every same-runtime/session source, the one destination, and each endpoint's exact current scope:

```powershell
python -m app.tools.relay_endpoint_repair --dry-run `
  --home "$env:USERPROFILE\.pallium" `
  --db-url "sqlite:///$env:USERPROFILE/.pallium/data/pallium-relay.db" `
  --manifest .\relay-repair.json `
  --claude-wake-dir "$env:USERPROFILE\.pallium\claude-wake" `
  --dispositions .\relay-dispositions.json `
  --source relay-session-... --scope relay-session-...=git:old-a `
  --source relay-session-... --scope relay-session-...=git:old-b `
  --destination relay-session-... --scope relay-session-...=git:destination
```

Review the complete endpoint/message/delivery preimage, reservation evidence, dispositions, and printed SHA-256. Version 2 manifests replace a claim token with a domain-separated SHA-256 fingerprint; the raw token is never written to the manifest or repair ledger. Canonical SQLite UTC-naive lease timestamps are interpreted as UTC. Codex wake history is process-local, so historical Codex deliveries remain `unknown` and cannot be adopted; use explicit `suppress` only after confirming the work is duplicate or will be resent. Claude adoption is allowed only when the installed durable capability and intent stores are valid, unchanged, and clean for that exact delivery/session/scope.

Apply only the reviewed file and exact digest:

```powershell
python -m app.tools.relay_endpoint_repair --apply `
  --home "$env:USERPROFILE\.pallium" `
  --db-url "sqlite:///$env:USERPROFILE/.pallium/data/pallium-relay.db" `
  --manifest .\relay-repair.json `
  --acknowledge-digest <sha256>
```

An identical committed retry returns the ledgered result. Any database, endpoint, TTL, claim lease/token fingerprint, inventory, or wake-evidence drift refuses before delivery mutation; rerun dry-run and review a new digest. Repair never merges endpoints: alias sends still route to the destination, exact sends/replies to a source still route to that source, and occupied scopes remain occupied. When finished, restart with `scripts/restart-service.ps1` and verify `/health`, `/status` (including `embedding_provider_ok`), and `/debug/queue/health` on the installed port.

The installed launcher must use a dependency-complete Python and the supported
`python -m app.run service run --port <port>` path: `service run` applies the
managed `~/.pallium/config/.env` and service configuration. Do not use the
deprecated `scripts/install-service.ps1` merely to repoint development code or
run a service from a temporary worktree.

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
| `/health` | `status: initializing` (503) | Still starting — schema initialization / vector load in progress. |
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
