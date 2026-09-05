# Claude Code Integration

This guide connects Claude Code to the local Pallium service. The integration
registers each session, records governed turns for Session History, delivers
Relay messages, and supports Pallium's optional derived-memory behavior.

## What You Get

### Relay

- send messages to another connected session; current integrations are Claude
  Code, Codex, and OpenCode
- receive attributed messages and reply to the sender
- wake an existing Claude Code session on qualified Windows installations
- keep undelivered messages for the next normal turn

### Session History

- record user and assistant turns from Claude Code sessions
- search earlier sessions broadly with `pallium_search_history`
- search one known exact work reference with `pallium_search_history_by_work_ref`
- open bounded surrounding turns with `pallium_expand_source`

### Optional derived memory

- extract compact decisions, findings, facts, constraints, and checkpoints
- retrieve or inject selected memory on later turns
- inspect, flag, and write memory through MCP tools

Claude Code wake is qualified on Windows. Linux and macOS wake remain
qualification work; those installations retain next-turn delivery.

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

Pallium runs as an always-on local service independent of Claude Code's
lifecycle. Multiple Claude Code sessions (same or different repos) share one
Pallium instance, isolated by `container_ref` (derived from the git remote
URL).

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

To manage the service:

| Command | Effect |
|---------|--------|
| `pallium service stop` | Stop the running service |
| `scripts/restart-service.ps1` | Restart the installed development service and clear stale child processes |
| `pallium service uninstall` | Remove OS registration (data preserved) |
| `pallium service uninstall --remove-data` | Remove registration and all data |

For debugging, run in the foreground:

```bash
pallium service run --port 19836
```

## 2. Register with Claude Code

```bash
pallium setup claude-code
```

This command:

1. Registers Pallium's session-bound stdio MCP server at Claude's user scope
2. Registers 4 hook scripts (SessionStart, UserPromptSubmit, Stop, PreCompact)
3. Appends Pallium agent instructions to `~/.claude/CLAUDE.md`
4. Creates the hook state directory for dedup tracking
5. Verifies the Pallium service is reachable

To remove the integration:

```bash
pallium setup claude-code --uninstall
```

## How It Works

### Hooks (Automatic)

Four hooks run automatically during Claude Code sessions:

| Hook | What it does |
|---|---|
| **SessionStart** | Registers or resumes the session and can provide orientation from earlier work. |
| **UserPromptSubmit** | Records the user turn, handles normal next-turn Relay delivery, and runs optional derived-memory lookup. |
| **Stop** | Records the assistant turn, marks the session idle, and participates in qualified wake/continuation delivery. |
| **PreCompact** | Preserves the latest session evidence and can re-query optional derived memory before compaction. |

Hooks are fail-safe and budget-capped. If Pallium is unavailable, they do not
block Claude Code.

### MCP Tools (Explicit)

The main operations are:

| Need | Tools |
|---|---|
| Send or reply through Relay | `pallium_relay_recipients`, `pallium_relay_name`, `pallium_relay_send`, `pallium_relay_reply`, `pallium_relay_status` |
| Search earlier sessions | `pallium_search_history`, then `pallium_expand_source` for surrounding turns |
| Use optional derived memory | `pallium_query`, `pallium_expand`, `pallium_flag_memory`, `pallium_ingest`, and the explicit memory-write tools |
| Check the service | `pallium_status` |

`pallium_relay_receive` and `pallium_relay_ack` are recovery or non-hook
integration tools. Do not use them in a session receiving Relay automatically
through hooks.

### Scoping

Each repo gets its own Pallium container, derived from the git remote URL:

| Scenario | Container |
|----------|-----------|
| Git repo with remote | `git:github.com/user/repo` |
| Git repo, no remote | `repo:<root-commit-hash>` |
| Not a git repo | `path:<hash-of-cwd>` |

Multiple Claude Code sessions in the same repo share the container but keep
distinct threads. Relay addressing and Session History work across those
sessions; configured derived memory follows the same scope.

### Optional derived-memory capture

Pallium extracts structured memory from ingested conversation turns:

- **Decisions** — "We chose X because Y"
- **Investigation outcomes** — "Root cause: stale cache after deploy"
- **Task checkpoints** — "Blocked on X, next step: Y"
- **Atomic facts** — names, dates, preferences, events
- **Interests and constraints** — expressed preferences and stated limits

Not everything is remembered. Short prompts (<20 chars), slash commands, and
duplicate prompts (within 5 minutes) are filtered. Assistant responses over
20K chars are skipped (avoids ingesting large tool dumps).

### Correcting derived memory

When an injected memory is incorrect, outdated, or nonsensical, Claude can
flag it using the `pallium_flag_memory` MCP tool. Each injected memory block
includes a `ref:<id>` that identifies it.

The `source_ref` parameter is optional — in local mode it auto-resolves to
the git user identity or `"local"`.

After 2 independent flags from different sessions, the memory is suppressed
and stops appearing in results. For details on the flagging mechanism, see
[agent-integration.md — Flagging Wrong Memories](agent-integration.md#flagging-wrong-memories).

## Verify It's Working

After setup, open two Claude Code sessions in the same Git repository.

### Verify Relay

1. In the second session, ask: “Use Pallium Relay to name this session `review`.”
2. In the first session, ask it to list Relay recipients and send a short message
   to `claude-code:@review`.
3. Confirm that the second session receives the attributed message and can reply.

Qualified Windows installations can start a new Claude Code turn. On other
paths, make a normal turn in the recipient session to collect the pending
message.

### Verify Session History

1. In one session, record a clear decision or investigation finding.
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
| Pallium tools are unavailable | Run `pallium service status`, then re-run `pallium setup claude-code`. |
| Relay recipient is missing | Make a normal turn in both sessions, confirm they use the same repository, then list recipients again. |
| Relay message remains pending | Make a normal recipient turn or inspect `pallium_relay_status`; active wake is not qualified on every platform. |
| Session History search is empty | Confirm the hooks are present in `~/.claude/settings.json` and search for a distinctive phrase from the earlier turn. |
| Hook errors or slow responses | Check `http://localhost:19836/debug/queue/health` and the configured embedding provider. |
| Derived memory is absent or irrelevant | Derived memory is optional. Use `pallium_query_debug` before changing prompts or policy. |
| MCP reports “Pallium not configured” | Re-run setup; it supplies `PALLIUM_BASE_URL` automatically. |

## Optional derived-memory policy

The optional `[injection.policy]` configuration controls whether each derived
memory type may appear proactively, only after an event, only on demand, or not
at all. It does not control Relay or deliberate Session History search.

See [Configuration — Injection Policy](configuration.md#injection-policy-abstention),
[Derived Memory](derived-memory.md#when-pallium-returns-nothing), and the
[detailed policy specification](specs/2026-06-27-injection-policy-abstention.md).

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
- Sessions in the same repo share Relay addressing and Session History
- Configured derived memory follows the same container scope
- Thread-level state doesn't leak between sessions
- SQLite WAL mode handles concurrent reads safely
- Per-session dedup state files eliminate race conditions
