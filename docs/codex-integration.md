# Codex Integration

This guide connects Codex to the local Pallium service. The integration
registers each task, records governed turns for Session History, delivers Relay
messages, and supports Pallium's optional derived-memory behavior.

## What You Get

### Relay

- send messages to another connected session; current integrations are Codex,
  Claude Code, and OpenCode
- receive attributed messages and reply to the sender
- wake loaded or unloaded exact Codex tasks on proven Windows paths
- keep undelivered messages for the next normal turn

### Session History

- record user and assistant turns from Codex tasks
- search earlier sessions deliberately with `pallium_search_history`
- open bounded surrounding turns with `pallium_expand_source`

### Optional derived memory

- extract compact decisions, findings, facts, constraints, and checkpoints
- retrieve or inject selected memory on later turns
- inspect, flag, and write memory through MCP tools

Windows exact-session wake is proven, but busy, interrupted, restart, telemetry,
and sustained-use qualification is still in progress. Other platforms retain
next-turn delivery.

## Architecture

```
┌────────────────────────┐
│     Codex CLI          │
│                        │
│  hooks ──────────────────── HTTP ──┐
│  MCP tools (stdio) ─────── HTTP ──┤
└────────────────────────┘           │
                                     ▼
                              ┌─────────────┐
                              │   Pallium   │
                              │local service│
                              │             │
                              │ port 19836  │
                              └──────┬──────┘
                                     │
                              ┌──────▼──────┐
                              │ ~/.pallium/ │
                              │   data/     │
                              └─────────────┘
```

Pallium runs as an always-on local service independent of Codex's lifecycle.
Multiple Codex sessions (same or different repos) share one Pallium instance,
isolated by `container_ref` (derived from the git remote URL).

## Prerequisites

- Python 3.12+ with Pallium installed (`pip install -e ".[dev,vector,mcp]"`)
- An LLM provider API key configured in `.env.local` for the current package-coupled installation
- Git (for container derivation from repos)

## 1. Start Pallium

Install and start the service (one-time):

```bash
pallium service install
```

This creates `~/.pallium/`, seeds config from your dev setup, downloads the
embedding model, starts the service on port 19836, and registers it for
auto-start at login.

Verify it's running:

```bash
pallium service status
```

For debugging, run in the foreground:

```bash
pallium service run --port 19836
```

## 2. Register with Codex

```bash
pallium setup codex
```

This command:

1. Enables the `codex_hooks` feature flag in `~/.codex/config.toml`
2. Registers Pallium's MCP server in `~/.codex/config.toml`
3. Registers 3 hook scripts (SessionStart, UserPromptSubmit, Stop) in `~/.codex/hooks.json`
4. Appends Pallium agent instructions to `~/.codex/AGENTS.md`
5. Creates the hook state directory for dedup tracking
6. Verifies the Pallium service is reachable

To remove the integration:

```bash
pallium setup codex --uninstall
```

To use a non-default port:

```bash
pallium setup codex --port 9999
```

## How It Works

### Hooks (Automatic)

Three hooks run automatically during Codex tasks:

| Hook | What it does |
|---|---|
| **SessionStart** | Registers or resumes the task and can provide orientation from earlier work. |
| **UserPromptSubmit** | Records the user turn, claims automatic Relay deliveries after turn admission, and runs optional derived-memory lookup. |
| **Stop** | Records the assistant turn and updates the task lifecycle used by Relay and history capture. |

Hooks are fail-safe and budget-capped. If Pallium is unavailable, they do not
block Codex. On a fresh start (`source: "clear"`), SessionStart skips optional
memory orientation.
### MCP Tools (Explicit)

The main operations are:

| Need | Tools |
|---|---|
| Send or reply through Relay | `pallium_relay_recipients`, `pallium_relay_name`, `pallium_relay_send`, `pallium_relay_reply`, `pallium_relay_status` |
| Search earlier sessions | `pallium_search_history`, then `pallium_expand_source` for surrounding turns |
| Use optional derived memory | `pallium_query`, `pallium_expand`, `pallium_flag_memory`, `pallium_rate_memory`, `pallium_ingest`, and the explicit memory-write tools |
| Check the service | `pallium_status` |

`pallium_relay_receive` and `pallium_relay_ack` are recovery or non-hook
integration tools. Do not use them in a task receiving Relay automatically
through hooks.
### Scoping

Each repo gets its own memory container, derived from the git remote URL:

| Scenario | Container |
|----------|-----------|
| Git repo with remote | `git:github.com/user/repo` |
| Git repo, no remote | `repo:<root-commit-hash>` |
| Not a git repo | `path:<hash-of-cwd>` |

Multiple Codex sessions on the same repo share the container (same memory)
but have distinct threads (different `session_id`).

### Shared history and derived memory

If you also use Claude Code with Pallium, both tools share the same memory
pool for a given repo (same `container_ref` derivation). A decision captured
in a Claude Code session is retrievable in a Codex session and vice versa.

The `source_type` field (`"codex"` vs `"claude-code"`) tracks provenance but
does not affect retrieval.

### What Gets Remembered

Pallium extracts structured memory from ingested conversation turns:

- **Decisions** — "We chose X because Y"
- **Investigation outcomes** — "Root cause: stale cache after deploy"
- **Task checkpoints** — "Blocked on X, next step: Y"
- **Atomic facts** — names, dates, preferences, events
- **Interests and constraints** — expressed preferences and stated limits

Not everything is remembered. Short prompts (<20 chars), slash commands, and
duplicate prompts (within 5 minutes) are filtered. Assistant responses over
20K chars are skipped.

## Verify It's Working

After setup, open a new Codex session in a git repo:

1. **Check service:** `curl http://localhost:19836/status` should return JSON
2. **First session:** type a meaningful prompt — you should see a
   `[Pallium memory ...]` block in the injected context
3. **Make a decision:** ask Codex to make a technical choice and explain it
4. **New session:** open a fresh session and ask about the topic — the
   decision from the previous session should appear in the injection

If memory doesn't appear:

- Check Pallium is running: `curl http://localhost:19836/status`
- Check hooks are registered: look in `~/.codex/hooks.json`
- Check MCP is configured: look for `[mcp_servers.pallium]` in `~/.codex/config.toml`. Relay receive uses the current Codex request metadata (top-level `threadId` and/or nested `x-codex-turn-metadata`, with every supplied task ID agreeing), not inherited environment IDs or model-supplied arguments; missing or conflicting metadata fails closed before any claim. Hook-delivery wake is independent of MCP recovery.
- Check MCP command: it should use an absolute Python executable with
  `args = ["-m", "app.run", "mcp"]`; this avoids blocked venv launcher
  stubs on Windows
- Check feature flag: ensure `codex_hooks = true` under `[features]` in config.toml
- Inspect retrieval: use the `pallium_query_debug` MCP tool

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No memory injected | Pallium not running | Start service or check port |
| No memory injected | Hooks not registered | Re-run `pallium setup codex` |
| No memory injected | Feature flag disabled | Ensure `codex_hooks = true` in `~/.codex/config.toml` |
| MCP tools not visible after setup | `pallium-mcp` command not resolvable by Codex | Re-run `pallium setup codex`; it writes an absolute executable path |
| "Pallium not configured" from MCP | `PALLIUM_BASE_URL` not set | Re-run `pallium setup codex` (it sets this automatically) |
| Memory injected but irrelevant | Early in project history | Give it more sessions to build up relevant memory |
| Hook timeout errors in stderr | Pallium responding slowly | Check processor queue, ensure embedding model is downloaded |

## Configuration

| Setting | Default | Override |
|---------|---------|----------|
| Service port | 19836 | `--port` on setup/install commands, or `PALLIUM_PORT` env var |
| HTTP timeout | 6s | Hardcoded (Codex allows 8s for hooks) |
| Session dedup window | 5 minutes | Hardcoded |
| Injection budget (SessionStart) | 1200 chars (~300 tokens) | Hardcoded |
| Injection budget (UserPromptSubmit) | 2400 chars (~600 tokens) | Hardcoded |
| Prompt min length | 20 chars | Hardcoded |
| Content-length gate (Stop) | 20K chars | Hardcoded |

## Differences from Claude Code Integration

| Aspect | Claude Code | Codex |
|--------|-------------|-------|
| Hook events | SessionStart, UserPromptSubmit, Stop, PreCompact | SessionStart, UserPromptSubmit, Stop |
| PreCompact | Re-injects before context compaction | Not available (no equivalent event) |
| Config files | `~/.claude/settings.json`, `~/.claude/CLAUDE.md` | `~/.codex/config.toml`, `~/.codex/hooks.json`, `~/.codex/AGENTS.md` |
| MCP transport | HTTP (streamable-http) | stdio (local process) |
| Setup command | `pallium setup claude-code` | `pallium setup codex` |

## Plugin Installation (Experimental)

The integration is also structured as a Codex plugin at `integrations/codex/`.
Plugin-local hooks may not execute reliably in current Codex CLI versions.
Use `pallium setup codex` as the primary installation method.

For testing the plugin path:

```json
{
  "plugins": [{
    "name": "pallium-memory",
    "source": { "type": "path", "path": "/path/to/pallium/integrations/codex" }
  }]
}
```

## Concurrent Sessions

Multiple Codex sessions on the same repo work correctly:

- Each session has its own thread (from `session_id`)
- Container-level memories are shared immediately
- Thread-level state doesn't leak between sessions
- SQLite WAL mode handles concurrent reads safely
- Per-session dedup state files eliminate race conditions
