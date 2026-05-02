# Claude Code Integration

This guide covers running Pallium as a local memory service for Claude Code.
After setup, every Claude Code session automatically receives relevant memory
from past sessions and contributes new memory for future ones.

## What You Get

- **Session orientation** — on session start, Claude sees recent decisions,
  progress, and open tasks from prior sessions in this repo
- **Per-turn memory** — each prompt gets relevant memories injected
  automatically before the model responds
- **Automatic extraction** — assistant responses are ingested and processed
  for reusable memory (decisions, findings, facts, checkpoints)
- **Compaction survival** — key context is re-injected before Claude Code
  compacts the conversation
- **Explicit tools** — Claude can query, flag, and ingest memories directly
  via MCP when automatic injection isn't enough

## Architecture

```
┌────────────────────────┐
│     Claude Code        │
│                        │
│  hooks ──────────────────── HTTP ──┐
│  MCP tools ──────────────── HTTP ──┤
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

Pallium runs as an always-on local service independent of Claude Code's
lifecycle. Multiple Claude Code sessions (same or different repos) share one
Pallium instance, isolated by `container_ref` (derived from the git remote
URL).

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

To manage the service:

| Command | Effect |
|---------|--------|
| `pallium service stop` | Stop the running service |
| `pallium service restart` | Stop and restart |
| `pallium service uninstall` | Remove OS registration (data preserved) |
| `pallium service uninstall --remove-data` | Remove registration and all data |

For debugging, run in the foreground:

```bash
pallium service run --port 19836
```

## 2. Register with Claude Code

```bash
python -m app.run setup claude-code
```

This command:

1. Registers Pallium's MCP server in `~/.claude/settings.json`
2. Registers 4 hook scripts (SessionStart, UserPromptSubmit, Stop, PreCompact)
3. Appends Pallium agent instructions to `~/.claude/CLAUDE.md`
4. Creates the hook state directory for dedup tracking
5. Verifies the Pallium service is reachable

To remove the integration:

```bash
python -m app.run setup claude-code --uninstall
```

## How It Works

### Hooks (Automatic)

Four hooks run automatically during every Claude Code session:

| Hook | When | What it does |
|------|------|-------------|
| **SessionStart** | Session begins | Queries Pallium for orientation (recent decisions, progress, open tasks). Injects ~300 tokens of context. |
| **UserPromptSubmit** | Each user message | Ingests the prompt as evidence, queries for relevant memories. Injects 400–800 tokens of context. |
| **Stop** | Model finishes responding | Reads the assistant response from the transcript and ingests it for extraction. No output. |
| **PreCompact** | Before context compaction | Re-queries for key context that would otherwise be lost. Injects 400–800 tokens. |

Hooks are safe by design:
- They always exit with code 0 (never block Claude Code)
- Errors go to stderr, never stdout (never pollute context)
- If Pallium is unreachable, hooks return empty output silently
- All output is budget-capped (never floods the context window)

### MCP Tools (Explicit)

When automatic injection isn't enough, Claude can use these tools directly:

| Tool | When to use |
|------|-------------|
| `pallium_query` | Injected context is empty or missing something specific |
| `pallium_get_evidence` | Need the original conversation behind a memory card |
| `pallium_flag_memory` | A memory contradicts current knowledge (see [flagging](#flagging-wrong-memories)) |
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

Multiple Claude Code sessions on the same repo share the container (same
memory) but have distinct threads (different `session_id`). Container-level
memories (decisions, facts) are visible across concurrent sessions.

### What Gets Remembered

Pallium extracts structured memory from ingested conversation turns:

- **Decisions** — "We chose X because Y"
- **Investigation outcomes** — "Root cause: stale cache after deploy"
- **Task checkpoints** — "Blocked on X, next step: Y"
- **Atomic facts** — names, dates, preferences, events
- **Interests and constraints** — expressed preferences and stated limits

Not everything is remembered. Short prompts (<20 chars), slash commands, and
duplicate prompts (within 5 minutes) are filtered. Assistant responses over
20K chars are skipped (avoids ingesting large tool dumps).

## Flagging Wrong Memories

When an injected memory is incorrect, outdated, or nonsensical, Claude can
flag it using the `pallium_flag_memory` MCP tool. Each injected memory block
includes a `ref:<id>` that identifies it.

The `source_ref` parameter is optional — in local mode it auto-resolves to
the git user identity or `"local"`.

After 2 independent flags from different sessions, the memory is suppressed
and stops appearing in results. For details on the flagging mechanism, see
[agent-integration.md — Flagging Wrong Memories](agent-integration.md#flagging-wrong-memories).

## Verify It's Working

After setup, open a new Claude Code session in a git repo:

1. **Check service:** `curl http://localhost:19836/status` should return JSON
2. **First session:** type a meaningful prompt — you should see a
   `[Pallium memory ...]` block in the context (visible in verbose mode)
3. **Make a decision:** ask Claude to make a technical choice and explain it
4. **New session:** open a fresh session and ask about the topic — the
   decision from the previous session should appear in the injection

If memory doesn't appear:

- Check Pallium is running: `curl http://localhost:19836/status`
- Check hooks are registered: look for "pallium" in `~/.claude/settings.json`
- Check processing: `curl http://localhost:19836/debug/queue/health`
- Inspect retrieval: use the `pallium_query_debug` MCP tool

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No memory injected | Pallium not running | Start service or check port |
| No memory injected | Hooks not registered | Re-run `python -m app.run setup claude-code` |
| Memory injected but irrelevant | Early in project history | Give it more sessions to build up relevant memory |
| Hook timeout errors in stderr | Pallium responding slowly | Check processor queue, ensure embedding model is downloaded |
| "Pallium not configured" from MCP | `PALLIUM_BASE_URL` not set | Setup command configures this automatically |

## Configuration

| Setting | Default | Override |
|---------|---------|----------|
| Service port | 19836 | `--port` on setup/install commands, or `PALLIUM_PORT` env var |
| HTTP timeout | 6s | Hardcoded (Claude Code allows 8s) |
| Session dedup window | 5 minutes | Hardcoded |
| Injection budget (SessionStart) | 1200 chars (~300 tokens) | Hardcoded |
| Injection budget (other hooks) | 2400 chars (~600 tokens) | Hardcoded |
| Prompt min length | 20 chars | Hardcoded |
| Content-length gate (Stop) | 20K chars | Hardcoded |

### Recommended Package Configuration

For the Claude Code integration, disable the `conversational_knowledge` (fact
extraction) package. Its atomic facts are redundant with the decisions and
investigation outcomes that `agent_conversation_memory` already extracts, and
they cannot compete for injection slots. Disabling it saves LLM tokens on every
ingested turn.

In `~/.pallium/config/pallium.toml`:

```toml
[semantic_packages.conversational_knowledge]
enabled = false
```

## Concurrent Sessions

Multiple Claude Code sessions on the same repo work correctly:

- Each session has its own thread (from `session_id`)
- Container-level memories are shared immediately
- Thread-level state doesn't leak between sessions
- SQLite WAL mode handles concurrent reads safely
- Per-session dedup state files eliminate race conditions
