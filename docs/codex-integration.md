# Codex Integration

This guide covers running Pallium as a local memory service for OpenAI Codex CLI.
After setup, every Codex session automatically receives relevant memory from
past sessions and contributes new memory for future ones.

## What You Get

- **Session orientation** — on session start, Codex sees recent decisions,
  progress, and open tasks from prior sessions in this repo
- **Per-turn memory** — each prompt gets relevant memories injected
  automatically before the model responds
- **Automatic extraction** — assistant responses are ingested and processed
  for reusable memory (decisions, findings, facts, checkpoints)
- **Explicit tools** — Codex can query, flag, and ingest memories directly
  via MCP when automatic injection isn't enough

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
                              │  (sidecar)  │
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
- An LLM provider API key configured in `.env.local`
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

Three hooks run automatically during every Codex session:

| Hook | When | What it does |
|------|------|-------------|
| **SessionStart** | Session begins (startup or resume) | Queries Pallium for orientation (recent decisions, progress, open tasks). Injects ~300 tokens of context. |
| **UserPromptSubmit** | Each user message | Ingests the prompt as evidence, queries for relevant memories. Injects 400–800 tokens of context. |
| **Stop** | Model finishes responding | Reads the assistant response from the transcript and ingests it for extraction. No output. |

Hooks are safe by design:
- They always exit with code 0 (never block Codex)
- Errors go to stderr, never stdout (never pollute context)
- If Pallium is unreachable, hooks return empty output silently
- All output is budget-capped (never floods the context window)
- On fresh start (`source: "clear"`), SessionStart skips injection

### MCP Tools (Explicit)

When automatic injection isn't enough, Codex can use these tools directly:

| Tool | When to use |
|------|-------------|
| `pallium_query` | Injected context is empty or missing something specific |
| `pallium_expand` | Need the full structured payload or original conversation behind a memory card |
| `pallium_flag_memory` | A memory contradicts current knowledge |
| `pallium_rate_memory` | Optionally rate clearly useful or off-topic injected memory |
| `pallium_ingest` | User explicitly asks to remember something |
| `pallium_query_debug` | Investigating why a memory wasn't found |
| `pallium_status` | Checking system health |

### Scoping

Each repo gets its own memory container, derived from the git remote URL:

| Scenario | Container |
|----------|-----------|
| Git repo with remote | `git:github.com/user/repo` |
| Git repo, no remote | `repo:<root-commit-hash>` |
| Not a git repo | `path:<hash-of-cwd>` |

Multiple Codex sessions on the same repo share the container (same memory)
but have distinct threads (different `session_id`).

### Cross-Agent Memory Sharing

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
- Check MCP is configured: look for `[mcp_servers.pallium]` in `~/.codex/config.toml`. Setup may include `env_vars = ["CODEX_THREAD_ID", "CODEX_SESSION_ID"]` as observed Codex compatibility inputs, not a public stable guarantee; Codex Desktop may not forward them to the MCP child, so `pallium_relay_receive` correctly fails closed until a runtime-owned handoff exists. Hook-delivery wake is independent of MCP recovery.
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
