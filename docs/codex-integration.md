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

1. Enables the `hooks` feature flag in `~/.codex/config.toml`
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

Each repo gets its own Pallium container, derived from the git remote URL:

| Scenario | Container |
|----------|-----------|
| Git repo with remote | `git:github.com/user/repo` |
| Git repo, no remote | `repo:<root-commit-hash>` |
| Not a git repo | `path:<hash-of-cwd>` |

Multiple Codex tasks in the same repo share the container but keep distinct
threads.

### Shared Session History

If you also use Claude Code with Pallium, both integrations record Session
History in the same repository container. A turn recorded in Claude Code is
searchable from Codex and vice versa. Configured derived memory follows the
same scope.

The `source_type` field (`"codex"` or `"claude-code"`) records where each item
came from; it does not change retrieval.

### Optional derived-memory capture

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

After setup, open two Codex tasks in the same Git repository.

### Verify Relay

1. In the second task, ask: “Use Pallium Relay to name this session `review`.”
2. In the first task, ask it to list Relay recipients and send a short message
   to `codex:@review`.
3. Confirm that the second task receives the attributed message and can reply.

Windows exact-session wake is proven but still completing broader lifecycle
qualification. On other paths, make a normal turn in the recipient task to
collect the pending message.

### Verify Session History

1. In one task, record a clear decision or investigation finding.
2. In the other, ask it to search Session History for that earlier work.
3. Expand the relevant result and confirm that the nearby messages provide the
   expected context.

This uses `pallium_search_history` followed by `pallium_expand_source`. It does
not depend on automatic derived-memory injection.

### Optional: verify derived memory

If derived memory is configured, use `pallium_query` for the earlier decision or
inspect an automatically injected memory block. No injection is also a valid
outcome when Pallium abstains; use `pallium_query_debug` to inspect why.

## Troubleshooting

| Symptom | Check |
|---|---|
| Pallium tools are unavailable | Run `pallium service status`, then re-run `pallium setup codex`. |
| Relay recipient is missing | Make a normal turn in both tasks, confirm they use the same repository, then list recipients again. |
| Relay message remains pending | Make a normal recipient turn or inspect `pallium_relay_status`; active wake is not qualified on every path. |
| Session History search is empty | Confirm hooks exist in `~/.codex/hooks.json` and search for a distinctive phrase from the earlier turn. |
| MCP tools are missing | Check `[mcp_servers.pallium]` in `~/.codex/config.toml` and re-run setup. |
| Hooks do not run | Ensure `hooks = true` under `[features]` in `~/.codex/config.toml`. |
| Derived memory is absent or irrelevant | Derived memory is optional. Use `pallium_query_debug` before changing prompts or policy. |
| MCP reports “Pallium not configured” | Re-run setup; it supplies `PALLIUM_BASE_URL` automatically. |

Relay recovery receive uses current Codex request metadata: top-level `threadId`
and/or nested `x-codex-turn-metadata`, with every supplied task ID agreeing.
Missing or conflicting metadata fails closed before a delivery is claimed.
Normal hook delivery is independent of this recovery path.

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

- Each task has its own thread (from `session_id`)
- Tasks in the same repo share Relay addressing and Session History
- Configured derived memory follows the same container scope
- Thread-level state doesn't leak between tasks
- SQLite WAL mode handles concurrent reads safely
- Per-session dedup state files eliminate race conditions
