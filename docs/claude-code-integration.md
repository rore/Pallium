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
- search earlier sessions deliberately with `pallium_search_history`
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
| No memory injected | Hooks not registered | Re-run `pallium setup claude-code` |
| Memory injected but irrelevant | Early in project history | Give it more sessions to build up relevant memory |
| Specific memory type stopped auto-injecting | Abstention policy enabled in `pallium.local.toml` | See [Abstention Policy](#abstention-policy-opt-in). Use `pallium_query` for explicit retrieval. |
| Hook timeout errors in stderr | Pallium responding slowly | Check processor queue, ensure embedding model is downloaded |
| "Pallium not configured" from MCP | `PALLIUM_BASE_URL` not set | Setup command configures this automatically |

## Abstention Policy (opt-in)

The default install proactively injects every memory type when relevant.
A per-type `[injection.policy]` block in `pallium.local.toml` can
demote specific types to event- or on-demand mode. See
[`docs/specs/2026-06-27-injection-policy-abstention.md`](specs/2026-06-27-injection-policy-abstention.md)
for the full spec; quick summary below.

**Modes** (per memory type, per container):

| Mode | Behavior |
|---|---|
| `proactive` | Auto-inject when score ≥ `min_score` |
| `event` | Drop from proactive; surfaced only by deterministic triggers (Phase 4 hooks) |
| `on_demand` | Drop from proactive; surfaced only by explicit `pallium_query` |
| `suspended` | Drop entirely (Phase 6 measurement / data-driven decision) |

**Deterministic triggers** added in Phase 4 — wired automatically by
`setup claude-code`:

| Hook | Trigger | Type surfaced |
|---|---|---|
| `SessionStart` | Prior open work matches current cwd/branch/paths | `task_checkpoint` |
| `PostToolUse` | Tool call failed (non-zero exit) | `investigation_outcome` matching error signature |
| `PostToolUse` | Same `(tool, target)` failed ≥3 times | `investigation_outcome` matching the retried operation |

Every Pallium query — proactive, triggered, or explicit — now carries a
`trigger_origin` label that lands in `query_audit_log.trigger_origin`
and `memory_usage_audit.trigger_origin` for measurement. Valid values:
`session_start_orientation`, `session_start_checkpoint`,
`user_prompt_submit`, `pre_compact`, `post_tool_failure`,
`retry_threshold`, `user_explicit`. Unknown values are rejected by the
API.

**Usage telemetry** (Phase 5a): every injected block now writes a row
to `memory_usage_audit` with `referenced_in_next_turn = NULL`. The
Phase 5b populator hook (not yet shipped) will fill in whether the
agent actually used the memory in its next turn. The
`GET /memory-usage-audit?query_audit_log_id=...` and
`POST /memory-usage-audit/{audit_row_id}` endpoints support the
populator.

**Default install does NOT enable the policy** — `pallium.local.toml`
ships without an `[injection.policy]` block, and the gate is a
bit-exact no-op when absent. To opt in, copy the commented block from
`pallium.example.toml` and uncomment. The recommended starting point
is:

- `task_checkpoint` → `event`
- `investigation_outcome` → `on_demand`
- `thread_summary` → `on_demand`
- `fact_summary` → `suspended`

Phase 1 data showed no type met ≥70% precision on holdout, so the
shipped example block does NOT enable proactive injection for any
type. Operators tighten via per-container overrides once Phase 6
measurement (4-week window after Phase 5b) yields usage rates that
justify it.

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
